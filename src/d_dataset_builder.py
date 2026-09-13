#!/usr/bin/env python3
import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass, field
from html import unescape
import json
import sys
import re
from textwrap import dedent
from typing import Any, Callable

import pandas as pd

from lib.checkpoint import (
    CheckpointState,
    append_checkpoint_records,
    build_default_checkpoint_base_path,
    iter_checkpoint_records,
    load_checkpoint_state,
    load_processed_item_ids_from_records,
    save_checkpoint_state,
)
from lib.csv_utils import load_csv_file
from lib.formats import get_json_from_noisy_json
from lib.llm import LLMClient, get_llm
from lib.logging import add_logging_args, get_logger, setup_logging
from lib.parallel import ParallelTask, run_parallel_tasks
from lib.prompt_templates import (
    format_attribute_schema,
    load_prompt_template_by_name,
    render_prompt_template,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """
    Configuration for constructing an LLM client.
    """

    provider: str
    model: str | None
    temperature: float | None
    reasoning: str | None
    api_key: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class DebugSettings:
    """
    Settings controlling optional debug output.
    """

    print_outputs: bool


class DatasetBuilderStopped(RuntimeError):
    """Raised after a checkpointed batch when cooperative stop is requested."""


def __get_args__() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Build a dataset by extracting spans and normalized values "
            "from factual statements using an LLM"
        )
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to input CSV file",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path to output CSV file",
    )
    parser.add_argument(
        "--attribute-schema",
        "-a",
        required=True,
        help="JSON file with nested attribute schema.",
    )
    parser.add_argument(
        "--provider",
        "-p",
        default="openai",
        help="LLM provider (default: openai)",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="LLM model name",
    )
    parser.add_argument(
        "--temperature",
        "-t",
        type=float,
        default=None,
        help="LLM temperature",
    )
    parser.add_argument(
        "--reasoning",
        default=None,
        help="LLM reasoning effort level",
    )
    parser.add_argument(
        "--method",
        default="extract_spans_and_values",
        help=(
            "Dataset building method: extract_spans_and_values, "
            "extract_spans_and_values_per_attribute, tag_spans, "
            "copy_spans_and_extract_values, langextract "
            '(default: "extract_spans_and_values")'
        ),
    )
    parser.add_argument(
        "--batch-size",
        "-b",
        type=int,
        default=10,
        help=("Number of sentences to process in parallel in one batch (default: 10)"),
    )
    parser.add_argument(
        "--sample",
        "-s",
        type=int,
        default=None,
        help="Limit to first N statements (default: all)",
    )
    parser.add_argument(
        "--checkpoint-path",
        default=None,
        help=(
            "Base path prefix for checkpoint state and records "
            "(default: <output>.checkpoint)"
        ),
    )
    parser.add_argument(
        "--print-outputs",
        action="store_true",
        help="Print raw LLM outputs for each processed row",
    )
    add_logging_args(parser)
    return parser.parse_args()


def load_input_data(
    path: str,
    sample: int | None = None,
) -> pd.DataFrame:
    """
    Load input CSV data.

    Parameters
    ----------
    path : str
        Path to the input CSV file.
    sample : int | None, default=None
        Maximum number of rows to keep.

    Returns
    -------
    pd.DataFrame
        Input data.
    """
    csv.field_size_limit(sys.maxsize)

    dataframe = load_csv_file(
        path,
        quoting=csv.QUOTE_ALL,
        quotechar='"',
        escapechar="\\",
        engine="python",
    )

    if sample is not None:
        dataframe = dataframe.head(sample)

    return pd.DataFrame(dataframe)


def load_json_file(file_path: str) -> dict[str, Any]:
    """
    Load JSON data from a file.

    Parameters
    ----------
    file_path : str
        Path to a JSON file.

    Returns
    -------
    dict[str, Any]
        Loaded JSON dictionary.
    """
    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def normalize_case_id(case_id: Any) -> str:
    """
    Convert a case identifier to a stable string representation.

    Parameters
    ----------
    case_id : Any
        Input case identifier.

    Returns
    -------
    str
        Normalized case identifier.
    """
    return str(case_id)


def get_attribute_cardinality(attribute_details: Any) -> str:
    """
    Determine attribute cardinality from schema details.

    Parameters
    ----------
    attribute_details : Any
        Attribute schema entry.

    Returns
    -------
    str
        Either ``single`` or ``multiple``.
    """
    if isinstance(attribute_details, dict):
        cardinality = attribute_details.get("cardinality", "single")
        return str(cardinality).lower()

    return "single"


def build_missing_attribute_value(
    attribute_details: Any,
) -> dict[str, str] | list[Any]:
    """
    Build a default value for a missing extracted attribute.

    Parameters
    ----------
    attribute_details : Any
        Schema details for the attribute.

    Returns
    -------
    dict[str, str] | list[Any]
        Default normalized attribute value.
    """
    if get_attribute_cardinality(attribute_details) == "multiple":
        return []

    value: dict[str, str] = {"span": "n/a"}

    if has_attribute_categories(attribute_details):
        value["class"] = "n/a"

    if has_attribute_format(attribute_details):
        value["value"] = "n/a"

    return value


def get_expected_attribute_keys(
    attribute_details: Any,
) -> list[str]:
    """
    Determine expected flat keys for an attribute value object.

    Parameters
    ----------
    attribute_details : Any
        Schema details for the attribute.

    Returns
    -------
    list[str]
        Expected keys for one extracted attribute item.
    """
    expected_keys = ["span"]

    if has_attribute_format(attribute_details):
        expected_keys.append("value")

    if has_attribute_categories(attribute_details):
        expected_keys.append("class")

    return expected_keys


def has_attribute_categories(attribute_details: Any) -> bool:
    """
    Determine whether an attribute defines category labels.

    Parameters
    ----------
    attribute_details : Any
        Schema details for the attribute.

    Returns
    -------
    bool
        ``True`` if the attribute defines categories.
    """
    categories = (
        attribute_details.get("categories")
        if isinstance(attribute_details, dict)
        else None
    )
    return isinstance(categories, dict) and len(categories) > 0


def has_attribute_format(attribute_details: Any) -> bool:
    """
    Determine whether an attribute defines a normalization format.

    Parameters
    ----------
    attribute_details : Any
        Schema details for the attribute.

    Returns
    -------
    bool
        ``True`` if the attribute defines a format rule.
    """
    format_value = (
        attribute_details.get("format") if isinstance(attribute_details, dict) else None
    )
    return isinstance(format_value, str) and format_value.strip() != ""


def convert_tags_to_json(tagged_sentence: str) -> dict[str, Any]:
    tag_re = re.compile(
        r"<(?P<tag>[A-Za-z_][\w\-]*)"
        r"(?P<attrs>\s+[^>]*)?>"
        r"(?P<span>.*?)"
        r"</\1>",
        re.DOTALL,
    )

    attr_re = re.compile(r'(?P<key>[A-Za-z_][\w\-]*)\s*=\s*"(?P<val>[^"]*)"')

    acc = defaultdict(list)

    for m in tag_re.finditer(tagged_sentence):
        tag = m.group("tag")
        attrs_raw = m.group("attrs") or ""
        span = unescape(m.group("span")).strip()

        attrs = {a.group("key"): a.group("val") for a in attr_re.finditer(attrs_raw)}

        item = {
            "span": span,
            "value": attrs.get("value", "n/a"),
            "class": attrs.get("class", "n/a"),
        }

        acc[tag].append(item)

    # collapse single-occurrence tags
    result = {}
    for tag, items in acc.items():
        result[tag] = items[0] if len(items) == 1 else items

    return result


def normalize_extracted_json(
    extracted_json: dict[str, Any],
    attribute_schema: dict[str, Any],
) -> dict[str, Any]:
    """
    Normalize extracted JSON to a stable top-level schema.

    Parameters
    ----------
    extracted_json : dict[str, Any]
        Parsed LLM output.
    attribute_schema : dict[str, Any]
        Full attribute schema.
    Returns
    -------
    dict[str, Any]
        Normalized JSON with all top-level attributes present.
    """
    normalized_json: dict[str, Any] = {}

    for attribute_name, attribute_details in attribute_schema.items():
        if attribute_name in extracted_json:
            normalized_json[attribute_name] = normalize_attribute_value_shape(
                attribute_value=extracted_json[attribute_name],
                attribute_details=attribute_details,
            )
        else:
            normalized_json[attribute_name] = build_missing_attribute_value(
                attribute_details=attribute_details,
            )

    return normalized_json


def normalize_attribute_value_shape(
    attribute_value: Any,
    attribute_details: Any,
) -> Any:
    """
    Normalize one attribute value to match schema cardinality.

    Parameters
    ----------
    attribute_value : Any
        Extracted attribute value.
    attribute_details : Any
        Schema details for the attribute.

    Returns
    -------
    Any
        Attribute value coerced to the expected cardinality shape.
    """
    if get_attribute_cardinality(attribute_details) != "multiple":
        return attribute_value

    if isinstance(attribute_value, list):
        return attribute_value

    return [attribute_value]


def flatten_attribute_value(
    attribute_name: str,
    attribute_value: Any,
    attribute_details: Any,
) -> dict[str, Any]:
    """
    Flatten a normalized attribute value into scalar table columns.

    Parameters
    ----------
    attribute_name : str
        Attribute name.
    attribute_value : Any
        Normalized attribute value.
    attribute_details : Any
        Schema details for the attribute.
    Returns
    -------
    dict[str, Any]
        Flat columns for one attribute.
    """
    flattened_value: dict[str, Any] = {}
    expected_keys = get_expected_attribute_keys(attribute_details)

    if isinstance(attribute_value, list):
        if not attribute_value:
            for key in expected_keys:
                flattened_value[f"{attribute_name}.0.{key}"] = "n/a"
            return flattened_value

        for index, item in enumerate(attribute_value):
            if not isinstance(item, dict):
                flattened_value[f"{attribute_name}.{index}"] = item
                continue

            for key in expected_keys:
                value = item.get(key, "n/a")
                flattened_value[f"{attribute_name}.{index}.{key}"] = value

        return flattened_value

    if isinstance(attribute_value, dict):
        for key in expected_keys:
            value = attribute_value.get(key, "n/a")
            flattened_value[f"{attribute_name}.{key}"] = value
        return flattened_value

    flattened_value[attribute_name] = attribute_value
    return flattened_value


def flatten_normalized_json(
    normalized_json: dict[str, Any],
    attribute_schema: dict[str, Any],
) -> dict[str, Any]:
    """
    Flatten normalized extraction JSON into table columns.

    Parameters
    ----------
    normalized_json : dict[str, Any]
        Normalized extraction JSON.
    attribute_schema : dict[str, Any]
        Full attribute schema.
    Returns
    -------
    dict[str, Any]
        Flat columns for the final dataframe row.
    """
    flattened_json: dict[str, Any] = {}

    for attribute_name, attribute_value in normalized_json.items():
        flattened_json.update(
            flatten_attribute_value(
                attribute_name=attribute_name,
                attribute_value=attribute_value,
                attribute_details=attribute_schema[attribute_name],
            )
        )

    return flattened_json


def flatten_extracted_json(
    extracted_json: dict[str, Any],
    attribute_schema: dict[str, Any],
) -> dict[str, Any]:
    """
    Flatten extracted JSON without relying on attribute schema.

    Parameters
    ----------
    extracted_json : dict[str, Any]
        Parsed LLM output.
    attribute_schema : dict[str, Any]
        Full attribute schema.

    Returns
    -------
    dict[str, Any]
        Flat columns for the extracted attributes only.
    """
    flattened_json: dict[str, Any] = {}

    for attribute_name, attribute_value in extracted_json.items():
        flattened_json.update(
            flatten_attribute_value(
                attribute_name=attribute_name,
                attribute_value=attribute_value,
                attribute_details=attribute_schema.get(attribute_name, {}),
            )
        )

    return flattened_json


def build_messages(
    prompt_template_name: str,
    user_content: str,
    template_variables: dict[str, str],
) -> list[dict[str, str]]:
    """
    Build LLM messages from a prompt template.

    Parameters
    ----------
    prompt_template_name : str
        Prompt template name used to build the system prompt.
    user_content : str
        User message content.
    template_variables : dict[str, str]
        Template variables used to render the system prompt.

    Returns
    -------
    list[dict[str, str]]
        LLM chat messages.
    """
    prompt_template = load_prompt_template_by_name(prompt_template_name)
    system_prompt = render_prompt_template(
        prompt_template,
        template_variables,
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def build_per_attribute_user_content(
    sentence: str,
    attribute_name: str,
    attribute_details: dict[str, Any],
) -> str:
    """
    Build the user payload for per-attribute extraction.

    Parameters
    ----------
    sentence : str
        Input factual sentence.
    attribute_name : str
        Attribute to extract.
    attribute_details : dict[str, Any]
        Schema definition for the selected attribute.

    Returns
    -------
    str
        User message with the stable sentence prefix and the changing
        attribute-specific suffix.
    """
    attribute_definition = format_attribute_schema({attribute_name: attribute_details})

    return dedent(
        f"""
        SENTENCE:
        {sentence}

        ATTRIBUTE NAME:
        {attribute_name}

        ATTRIBUTE DEFINITION:
        {attribute_definition}
        """
    ).strip()


def is_attribute_value_payload(value: Any) -> bool:
    """
    Detect the unwrapped payload shape for one extracted attribute.

    Parameters
    ----------
    value : Any
        Parsed JSON fragment produced by the LLM.

    Returns
    -------
    bool
        ``True`` when the value is either one attribute object with
        ``span``/``value``/``class`` keys or a list of such objects.

    Notes
    -----
    In ``extract_spans_and_values_per_attribute`` mode the prompt asks for a
    single attribute at a time. The model may therefore return either the
    wrapped shape ``{"attributeName": {...}}`` or just the inner payload
    ``{"span": "...", "value": "..."}``. This helper identifies the second
    case so the caller can still attach the payload to the current attribute
    name.
    """
    if isinstance(value, list):
        return all(is_attribute_value_payload(item) for item in value)

    if not isinstance(value, dict):
        return False

    allowed_keys = {"span", "value", "class"}
    payload_keys = set(value)
    return "span" in payload_keys and payload_keys.issubset(allowed_keys)


def extract_attributes_one_by_one(
    llm: LLMClient,
    sentence: str,
    attribute_schema: dict[str, Any],
    debug_settings: DebugSettings,
) -> dict[str, Any]:
    """
    Extract attributes by iterating over the schema one attribute at a time.

    Parameters
    ----------
    llm : LLMClient
        LLM client used for extraction.
    sentence : str
        Input factual sentence.
    attribute_schema : dict[str, Any]
        Full attribute schema.
    debug_settings : DebugSettings
        Settings controlling optional debug output.

    Returns
    -------
    dict[str, Any]
        Aggregated extraction JSON keyed by attribute name.
    """
    extracted_json: dict[str, Any] = {}

    for attribute_name, attribute_details in attribute_schema.items():
        messages = build_messages(
            prompt_template_name="extract_spans_and_values_per_attribute_prompt",
            user_content=build_per_attribute_user_content(
                sentence=sentence,
                attribute_name=attribute_name,
                attribute_details=attribute_details,
            ),
            template_variables={},
        )
        raw_response = llm.chat(messages)
        if debug_settings.print_outputs:
            logger.debug("OUTPUT for attribute %s\n%s", attribute_name, raw_response)
        parsed_response = get_json_from_noisy_json(raw_response)

        if isinstance(parsed_response, dict) and attribute_name in parsed_response:
            extracted_json[attribute_name] = parsed_response[attribute_name]
            continue

        if is_attribute_value_payload(parsed_response):
            extracted_json[attribute_name] = parsed_response

    return extracted_json


def order_output_columns(
    output_dataframe: pd.DataFrame,
    attribute_schema: dict[str, Any] | None,
) -> pd.DataFrame:
    """
    Reorder dataframe columns according to attribute schema order.

    Parameters
    ----------
    output_dataframe : pd.DataFrame
        Output dataframe before column ordering.
    attribute_schema : dict[str, Any] | None
        Optional attribute schema.

    Returns
    -------
    pd.DataFrame
        Dataframe with reordered columns.
    """

    def get_column_sort_key(column_name: str) -> tuple[int, int, str]:
        """
        Build a stable sort key for flattened attribute columns.

        Parameters
        ----------
        column_name : str
            Full dataframe column name.

        Returns
        -------
        tuple[int, int, str]
            Sort key ordered by occurrence index and field type.
        """
        suffix = column_name.split(".", maxsplit=1)[1]
        parts = suffix.split(".")

        if len(parts) == 1:
            field_name = parts[0]
            field_order = {"span": 0, "value": 1, "class": 2}
            return (-1, field_order.get(field_name, 99), field_name)

        if len(parts) == 2 and parts[0].isdigit():
            index = int(parts[0])
            field_name = parts[1]
            field_order = {"span": 0, "value": 1, "class": 2}
            return (index, field_order.get(field_name, 99), field_name)

        return (999999, 999999, suffix)

    if attribute_schema is None:
        return output_dataframe

    fixed_columns = [
        column_name
        for column_name in [
            "judgement_slt_id",
            "judgement_factual_sentence",
            "tagged_sentence",
        ]
        if column_name in output_dataframe.columns
    ]
    ordered_columns = list(fixed_columns)

    for attribute_name in attribute_schema:
        matching_columns = [
            column_name
            for column_name in output_dataframe.columns
            if column_name.startswith(f"{attribute_name}.")
        ]
        matching_columns.sort(key=get_column_sort_key)
        ordered_columns.extend(matching_columns)

    remaining_columns = [
        column_name
        for column_name in output_dataframe.columns
        if column_name not in ordered_columns
    ]
    ordered_columns.extend(remaining_columns)

    return output_dataframe.loc[:, ordered_columns]


def validate_method_inputs(
    method: str,
    dataframe: pd.DataFrame,
    attribute_schema: dict[str, Any] | None,
) -> None:
    """
    Validate schema inputs required by the selected method.

    Parameters
    ----------
    method : str
        Dataset building method.
    dataframe : pd.DataFrame
        Input dataframe.
    attribute_schema : dict[str, Any] | None
        Optional attribute schema.
    Raises
    ------
    ValueError
        If the selected method is missing required inputs.
    """
    if method in {
        "extract_spans_and_values",
        "extract_spans_and_values_per_attribute",
    }:
        if attribute_schema is None:
            raise ValueError(f'Method "{method}" requires --attribute-schema.')
        return

    if method == "tag_spans":
        if attribute_schema is None:
            raise ValueError('Method "tag_spans" requires --attribute-schema.')
        return

    if method == "copy_spans_and_extract_values":
        if attribute_schema is None:
            raise ValueError(f'Method "{method}" requires --attribute-schema.')
        if "tagged_sentence" not in dataframe.columns:
            raise ValueError(
                'Method "copy_spans_and_extract_values" requires a '
                '"tagged_sentence" column in the input dataset.'
            )
        return

    if method == "langextract":
        return

    raise ValueError(f"Unsupported dataset building method: {method}")


def extract_row(
    llm_settings: LLMSettings,
    debug_settings: DebugSettings,
    row: pd.Series,
    attribute_schema: dict[str, Any] | None,
    method: str,
) -> dict[str, Any]:
    """
    Extract dataset JSON for a single dataframe row.

    Parameters
    ----------
    llm_settings : LLMSettings
        Settings used to construct the LLM client.
    debug_settings : DebugSettings
        Settings controlling optional debug output.
    row : pd.Series
        Input row.
    attribute_schema : dict[str, Any] | None
        Optional attribute schema.
    method : str
        Dataset building method.

    Returns
    -------
    dict[str, Any]
        Output row for the final dataframe.
    """
    case_id = row["judgement_slt_id"]
    sentence = row["judgement_factual_sentence"]
    llm = get_llm(
        provider=llm_settings.provider,
        model=llm_settings.model,
        temperature=llm_settings.temperature,
        reasoning=llm_settings.reasoning,
        api_key=llm_settings.api_key,
    )

    tagged_sentence = None
    extracted_json = None

    if method == "extract_spans_and_values":
        assert attribute_schema is not None

        messages = build_messages(
            prompt_template_name="extract_spans_and_values_prompt",
            user_content=sentence,
            template_variables={
                "attribute_schema": format_attribute_schema(attribute_schema),
            },
        )
        raw_response = llm.chat(messages)
        if debug_settings.print_outputs:
            logger.debug("OUTPUT for case %s\n%s", case_id, raw_response)
        extracted_json = get_json_from_noisy_json(raw_response)

    elif method == "extract_spans_and_values_per_attribute":
        assert attribute_schema is not None
        extracted_json = extract_attributes_one_by_one(
            llm=llm,
            sentence=sentence,
            attribute_schema=attribute_schema,
        )

    elif method == "tag_spans":
        assert attribute_schema is not None

        tagging_messages = build_messages(
            prompt_template_name="tag_spans_prompt",
            user_content=sentence,
            template_variables={
                "attribute_schema": format_attribute_schema(attribute_schema),
            },
        )
        tagged_sentence = llm.chat(tagging_messages)
        extracted_json = convert_tags_to_json(tagged_sentence)

    elif method == "copy_spans_and_extract_values":
        assert attribute_schema is not None

        tagged_sentence = row["tagged_sentence"]
        derivation_messages = build_messages(
            prompt_template_name="copy_spans_and_extract_values_prompt",
            user_content=tagged_sentence,
            template_variables={
                "attribute_schema": format_attribute_schema(attribute_schema),
            },
        )
        raw_response = llm.chat(derivation_messages)
        extracted_json = get_json_from_noisy_json(raw_response)

    elif method == "langextract":
        raise NotImplementedError('Method "langextract" is not implemented yet.')

    else:
        raise ValueError(f"Unsupported dataset building method: {method}")

    output_row: dict[str, Any] = {
        "judgement_slt_id": case_id,
        "judgement_factual_sentence": sentence,
    }

    if tagged_sentence:
        output_row["tagged_sentence"] = tagged_sentence
    if extracted_json is not None and attribute_schema is not None:
        normalized_json = normalize_extracted_json(
            extracted_json=extracted_json,
            attribute_schema=attribute_schema,
        )
        flattened_json = flatten_normalized_json(
            normalized_json=normalized_json,
            attribute_schema=attribute_schema,
        )
        output_row.update(flattened_json)

    logger.info("Processed case %s", case_id)
    return output_row


def build_checkpoint_record(output_row: dict[str, Any]) -> dict[str, Any]:
    """
    Build one checkpoint record from a processed output row.

    Parameters
    ----------
    output_row : dict[str, Any]
        Processed dataset builder output row.

    Returns
    -------
    dict[str, Any]
        Serializable checkpoint record.
    """
    return {
        "item_id": normalize_case_id(output_row["judgement_slt_id"]),
        "output_row": output_row,
    }


def load_output_rows_from_checkpoint(
    checkpoint_path: str,
) -> list[dict[str, Any]]:
    """
    Load processed output rows from checkpoint records.

    Parameters
    ----------
    checkpoint_path : str
        Base path prefix for the checkpoint store.

    Returns
    -------
    list[dict[str, Any]]
        Output rows reconstructed from checkpoint records.
    """
    output_rows: list[dict[str, Any]] = []

    for record in iter_checkpoint_records(checkpoint_path):
        output_row = record.get("output_row")
        if isinstance(output_row, dict):
            output_rows.append(output_row)

    return output_rows


def run_dataset_builder(
    dataframe: pd.DataFrame,
    llm_settings: LLMSettings,
    debug_settings: DebugSettings,
    attribute_schema: dict[str, Any] | None,
    method: str,
    batch_size: int,
    checkpoint_path: str,
    progress_callback: Callable[[int, int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> pd.DataFrame:
    """
    Build dataset rows using batched parallel LLM requests.

    Parameters
    ----------
    dataframe : pd.DataFrame
        Filtered input data.
    llm_settings : LLMSettings
        Settings used to construct the LLM client.
    debug_settings : DebugSettings
        Settings controlling optional debug output.
    attribute_schema : dict[str, Any] | None
        Optional attribute schema.
    method : str
        Dataset building method.
    batch_size : int
        Number of rows processed in parallel at once.
    checkpoint_path : str
        Base path prefix for the checkpoint store.
    progress_callback : Callable[[int, int, int], None] | None, default=None
        Optional callback receiving completed, total, and failed row counts
        after checkpoint resume is loaded and after each processed batch.
    should_stop : Callable[[], bool] | None, default=None
        Optional cooperative-stop callback. A requested stop is honored before
        starting another batch and after the current batch is checkpointed.

    Returns
    -------
    pd.DataFrame
        Output dataframe ready for CSV export.
    """
    validate_method_inputs(
        method=method,
        dataframe=dataframe,
        attribute_schema=attribute_schema,
    )

    checkpoint_state = load_checkpoint_state(checkpoint_path)
    processed_case_ids = set(checkpoint_state.processed_item_ids)
    if not processed_case_ids:
        processed_case_ids.update(load_processed_item_ids_from_records(checkpoint_path))

    rows = [
        row
        for _, row in dataframe.iterrows()
        if normalize_case_id(row["judgement_slt_id"]) not in processed_case_ids
    ]
    skipped_resumed_rows = len(dataframe) - len(rows)
    if skipped_resumed_rows > 0:
        logger.info(
            "Skipping %d rows already present in checkpoint", skipped_resumed_rows
        )

    failed_row_count = 0
    failure_rows: list[dict[str, str]] = []
    if progress_callback is not None:
        progress_callback(skipped_resumed_rows, len(dataframe), failed_row_count)
    if (
        should_stop is not None
        and should_stop()
        and skipped_resumed_rows < len(dataframe)
    ):
        raise DatasetBuilderStopped("Dataset generation stopped at a checkpoint.")

    successful_case_ids = set(processed_case_ids)

    for batch_start in range(0, len(rows), batch_size):
        if should_stop is not None and should_stop():
            raise DatasetBuilderStopped("Dataset generation stopped at a checkpoint.")
        batch_rows = rows[batch_start : batch_start + batch_size]
        batch_end = batch_start + len(batch_rows) - 1
        logger.info("Processing rows %d to %d", batch_start, batch_end)

        tasks = [
            ParallelTask(
                case_id=row["judgement_slt_id"],
                payload=row,
            )
            for row in batch_rows
        ]

        successful_results, failures = run_parallel_tasks(
            tasks=tasks,
            worker=lambda row: extract_row(
                llm_settings=llm_settings,
                debug_settings=debug_settings,
                row=row,
                attribute_schema=attribute_schema,
                method=method,
            ),
            on_failure="collect",
        )

        for failure in failures:
            logger.warning(
                "Skipping case %s because extraction failed: %s",
                failure.task.case_id,
                failure.error,
            )
        if failures:
            batch_failure_rows = [
                {
                    "sentence_id": str(failure.task.case_id),
                    "sentence_raw": str(
                        failure.task.payload.get("judgement_factual_sentence", "")
                    ),
                    "error_type": type(failure.error).__name__,
                    "error_message": str(failure.error),
                }
                for failure in failures
            ]
            failure_rows.extend(batch_failure_rows)
        failed_row_count += len(failures)

        batch_output_rows = [output_row for _, output_row in successful_results]
        batch_checkpoint_records = [
            build_checkpoint_record(output_row=output_row)
            for output_row in batch_output_rows
        ]
        append_checkpoint_records(
            checkpoint_path,
            batch_checkpoint_records,
        )

        successful_case_ids.update(
            normalize_case_id(output_row["judgement_slt_id"])
            for output_row in batch_output_rows
        )
        save_checkpoint_state(
            checkpoint_path,
            CheckpointState(
                processed_item_ids=frozenset(successful_case_ids),
                metadata={
                    "record_count": len(successful_case_ids),
                    "module": "d_dataset_builder",
                },
            ),
        )
        completed_row_count = min(
            len(dataframe), batch_start + len(batch_rows) + skipped_resumed_rows
        )
        if progress_callback is not None:
            progress_callback(
                completed_row_count,
                len(dataframe),
                failed_row_count,
            )
        if (
            should_stop is not None
            and should_stop()
            and completed_row_count < len(dataframe)
        ):
            raise DatasetBuilderStopped("Dataset generation stopped at a checkpoint.")

    output_rows = load_output_rows_from_checkpoint(checkpoint_path)
    output_dataframe = pd.DataFrame(output_rows)
    output_dataframe = output_dataframe.fillna("n/a")
    output_dataframe = order_output_columns(
        output_dataframe=output_dataframe,
        attribute_schema=attribute_schema,
    )
    output_dataframe.attrs["failure_rows"] = failure_rows
    return output_dataframe


if __name__ == "__main__":
    args = __get_args__()
    setup_logging(args.verbose, args.log_file, force_debug=args.print_outputs)

    attribute_schema = (
        load_json_file(args.attribute_schema)
        if args.attribute_schema is not None
        else None
    )

    dataframe = load_input_data(args.input, args.sample)

    llm_settings = LLMSettings(
        provider=args.provider,
        model=args.model,
        temperature=args.temperature,
        reasoning=args.reasoning,
    )
    debug_settings = DebugSettings(
        print_outputs=args.print_outputs,
    )

    checkpoint_path = (
        args.checkpoint_path
        if args.checkpoint_path is not None
        else build_default_checkpoint_base_path(args.output)
    )

    output_dataframe = run_dataset_builder(
        dataframe=dataframe,
        llm_settings=llm_settings,
        debug_settings=debug_settings,
        attribute_schema=attribute_schema,
        method=args.method,
        batch_size=args.batch_size,
        checkpoint_path=checkpoint_path,
    )
    output_dataframe.to_csv(args.output, index=False)
    logger.info("Results saved to %s", args.output)
