#!/usr/bin/env python3
import argparse
from collections import Counter
import csv
from dataclasses import dataclass
import json
import re
import sys
from typing import Any, Literal

import pandas as pd

from lib.csv_utils import load_csv_file
from lib.formats import get_json_from_noisy_json
from lib.llm import LLMClient, get_llm
from lib.logging import add_logging_args, get_logger, setup_logging
from lib.prompt_templates import (
    load_prompt_template_by_name,
    render_prompt_template,
)

logger = get_logger(__name__)


NormalizationClass = Literal[
    "standardizable_by_category",
    "standardizable_by_format",
    "split_into_multiple_attributes",
    "not_standardizable",
]
Cardinality = Literal["single", "multiple"]

SPAN_COLUMN_PATTERN = re.compile(r"^(?P<attribute_name>[^.]+)(?:\.\d+)?\.span$")
VALID_NORMALIZATION_CLASSES: tuple[NormalizationClass, ...] = (
    "standardizable_by_category",
    "standardizable_by_format",
    "split_into_multiple_attributes",
    "not_standardizable",
)


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """
    Configuration for constructing an LLM client.
    """

    provider: str
    model: str | None
    temperature: float | None
    reasoning: str | None


@dataclass(frozen=True, slots=True)
class DebugSettings:
    """
    Settings controlling optional debug output.
    """

    print_prompts: bool
    print_outputs: bool


@dataclass(frozen=True, slots=True)
class AttributeValueSet:
    """
    Aggregated extracted values for one attribute.
    """

    attribute_name: str
    total_value_count: int
    unique_value_count: int
    sentence_count: int
    sentences_with_value_count: int
    sentences_with_single_value_count: int
    sentences_with_multiple_values_count: int
    single_value_ratio: float
    cardinality: Cardinality
    sampled_values: list[str]


@dataclass(frozen=True, slots=True)
class NormalizationDecision:
    """
    Normalization decision assigned to one attribute.
    """

    attribute_name: str
    cardinality: Cardinality
    normalization_class: NormalizationClass
    categories: dict[str, str] | None = None
    formatting_rule: str | None = None


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
            "Classify extracted attributes by normalization strategy "
            "using aggregated span values and an LLM"
        )
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to input CSV file with extracted span columns",
    )
    parser.add_argument(
        "--attribute-schema",
        "-a",
        required=True,
        help="Path to input attribute schema JSON file",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path to output JSON file with enriched attribute schema",
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
        "--max-sampled-values",
        type=int,
        default=50,
        help=(
            "Maximum number of most frequent values shown to the LLM per "
            "attribute (default: 50)"
        ),
    )
    parser.add_argument(
        "--single-cardinality-threshold",
        type=float,
        default=0.9,
        help=(
            "Minimum share of non-empty sentences in which an attribute "
            'appears only once to classify it as "single" (default: 0.9)'
        ),
    )
    parser.add_argument(
        "--print-prompts",
        action="store_true",
        help="Print LLM prompt messages before each attribute classification",
    )
    parser.add_argument(
        "--print-outputs",
        action="store_true",
        help="Print raw LLM outputs for each attribute classification",
    )
    add_logging_args(parser)
    return parser.parse_args()


def load_input_data(path: str) -> pd.DataFrame:
    """
    Load input CSV data.

    Parameters
    ----------
    path : str
        Path to the input CSV file.

    Returns
    -------
    pd.DataFrame
        Input data.
    """
    csv.field_size_limit(sys.maxsize)
    return load_csv_file(
        path,
        quoting=csv.QUOTE_MINIMAL,
        quotechar='"',
        escapechar="\\",
        engine="python",
    )


def load_json_file(path: str) -> dict[str, Any]:
    """
    Load JSON data from a file.

    Parameters
    ----------
    path : str
        Path to a JSON file.

    Returns
    -------
    dict[str, Any]
        Loaded JSON dictionary.
    """
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def validate_attribute_schema(
    attribute_schema: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    Validate that attribute schema entries are nested objects.

    Parameters
    ----------
    attribute_schema : dict[str, Any]
        Attribute schema to validate.

    Returns
    -------
    dict[str, dict[str, Any]]
        Validated attribute schema.

    Raises
    ------
    ValueError
        If the schema has an unsupported shape.
    """
    validated_schema: dict[str, dict[str, Any]] = {}

    for attribute_name, attribute_details in attribute_schema.items():
        if not isinstance(attribute_details, dict):
            raise ValueError(
                "Each attribute definition must be an object with at least "
                f'"description". Invalid value for "{attribute_name}".'
            )

        if "description" not in attribute_details:
            raise ValueError(
                "Each attribute definition must be an object with at least "
                f'"description". Missing it for "{attribute_name}".'
            )

        validated_schema[attribute_name] = dict(attribute_details)

    return validated_schema


def get_attribute_span_columns(dataframe: pd.DataFrame) -> dict[str, list[str]]:
    """
    Collect span columns grouped by attribute name.

    Parameters
    ----------
    dataframe : pd.DataFrame
        Input dataframe containing flattened span columns.

    Returns
    -------
    dict[str, list[str]]
        Mapping from attribute name to matching span columns.
    """
    attribute_columns: dict[str, list[str]] = {}

    for column_name in dataframe.columns:
        match = SPAN_COLUMN_PATTERN.match(column_name)
        if match is None:
            continue

        attribute_name = match.group("attribute_name")
        attribute_columns.setdefault(attribute_name, []).append(column_name)

    for attribute_name in attribute_columns:
        attribute_columns[attribute_name].sort()

    return attribute_columns


def should_keep_value(value: Any) -> bool:
    """
    Decide whether an extracted value should be kept for aggregation.

    Parameters
    ----------
    value : Any
        Candidate cell value.

    Returns
    -------
    bool
        ``True`` if the value should be kept.
    """
    if pd.isna(value):
        return False

    normalized_value = str(value).strip()
    return normalized_value not in {"", "n/a"}


def get_sentence_attribute_values(row: pd.Series) -> list[str]:
    """
    Collect normalized attribute values from one sentence row slice.

    Parameters
    ----------
    row : pd.Series
        Row slice containing only columns for one attribute.

    Returns
    -------
    list[str]
        Normalized non-empty values for the attribute in the sentence.
    """
    sentence_values: list[str] = []

    for value in row:
        if not should_keep_value(value):
            continue
        sentence_values.append(str(value).strip())

    return sentence_values


def collect_attribute_values(
    dataframe: pd.DataFrame,
    max_sampled_values: int,
    single_cardinality_threshold: float,
) -> list[AttributeValueSet]:
    """
    Aggregate extracted span values per attribute.

    Parameters
    ----------
    dataframe : pd.DataFrame
        Input dataframe containing flattened span columns.
    max_sampled_values : int
        Maximum number of most frequent values to keep per attribute.
    single_cardinality_threshold : float
        Minimum share of non-empty sentences in which the attribute
        appears only once to classify it as ``single``.

    Returns
    -------
    list[AttributeValueSet]
        Aggregated values for each attribute.
    """
    attribute_columns = get_attribute_span_columns(dataframe)
    attribute_value_sets: list[AttributeValueSet] = []

    for attribute_name, column_names in attribute_columns.items():
        per_sentence_value_counts: list[int] = []
        per_sentence_values: list[list[str]] = []

        for _, row in dataframe[column_names].iterrows():
            sentence_values = get_sentence_attribute_values(row)
            per_sentence_values.append(sentence_values)
            per_sentence_value_counts.append(len(sentence_values))

        sentences_with_value_count = sum(
            1 for value_count in per_sentence_value_counts if value_count > 0
        )
        sentences_with_single_value_count = sum(
            1 for value_count in per_sentence_value_counts if value_count == 1
        )
        sentences_with_multiple_values_count = sum(
            1 for value_count in per_sentence_value_counts if value_count > 1
        )
        if sentences_with_value_count == 0:
            single_value_ratio = 1.0
        else:
            single_value_ratio = (
                sentences_with_single_value_count / sentences_with_value_count
            )
        cardinality: Cardinality = (
            "single"
            if single_value_ratio >= single_cardinality_threshold
            else "multiple"
        )
        counter: Counter[str] = Counter()

        if cardinality == "single":
            for sentence_values in per_sentence_values:
                if not sentence_values:
                    continue
                combined_value = " | ".join(sentence_values)
                counter[combined_value] += 1
        else:
            for sentence_values in per_sentence_values:
                for value in sentence_values:
                    counter[value] += 1

        sampled_values = [
            f"{value} [{count}]"
            for value, count in counter.most_common(max_sampled_values)
        ]
        attribute_value_sets.append(
            AttributeValueSet(
                attribute_name=attribute_name,
                total_value_count=sum(counter.values()),
                unique_value_count=len(counter),
                sentence_count=len(per_sentence_value_counts),
                sentences_with_value_count=sentences_with_value_count,
                sentences_with_single_value_count=(sentences_with_single_value_count),
                sentences_with_multiple_values_count=(
                    sentences_with_multiple_values_count
                ),
                single_value_ratio=single_value_ratio,
                cardinality=cardinality,
                sampled_values=sampled_values,
            )
        )

    attribute_value_sets.sort(key=lambda item: item.attribute_name)
    return attribute_value_sets


def build_messages(attribute_value_set: AttributeValueSet) -> list[dict[str, str]]:
    """
    Build LLM messages for one attribute normalization decision.

    Parameters
    ----------
    attribute_value_set : AttributeValueSet
        Aggregated values for one attribute.

    Returns
    -------
    list[dict[str, str]]
        LLM chat messages.
    """
    prompt_template = load_prompt_template_by_name("semantic_normalizer_prompt")
    sampled_values = "\n".join(
        f"- {value}" for value in attribute_value_set.sampled_values
    )
    if sampled_values == "":
        sampled_values = "- n/a"

    system_prompt = render_prompt_template(
        prompt_template,
        {
            "attribute_name": attribute_value_set.attribute_name,
            "total_value_count": str(attribute_value_set.total_value_count),
            "unique_value_count": str(attribute_value_set.unique_value_count),
            "cardinality": attribute_value_set.cardinality,
            "sampled_values": sampled_values,
        },
    )

    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": ("Return the normalization class for this attribute as JSON."),
        },
    ]


def parse_normalization_class(response_json: dict[str, Any]) -> NormalizationClass:
    """
    Validate the normalization class returned by the LLM.

    Parameters
    ----------
    response_json : dict[str, Any]
        Parsed LLM response.

    Returns
    -------
    NormalizationClass
        Validated normalization class.

    Raises
    ------
    ValueError
        If the response does not contain a supported class.
    """
    raw_value = response_json.get("normalization_class")

    if raw_value not in VALID_NORMALIZATION_CLASSES:
        raise ValueError(
            f"Unsupported normalization class returned by the LLM: {raw_value}"
        )

    return raw_value


def parse_categories(response_json: dict[str, Any]) -> dict[str, str] | None:
    """
    Validate proposed categories returned by the LLM.

    Parameters
    ----------
    response_json : dict[str, Any]
        Parsed LLM response.

    Returns
    -------
    dict[str, str] | None
        Validated category mapping or ``None``.

    Raises
    ------
    ValueError
        If the category structure is invalid.
    """
    raw_categories = response_json.get("categories")

    if raw_categories is None:
        return None

    if not isinstance(raw_categories, dict):
        raise ValueError("LLM returned invalid categories. Expected an object.")

    validated_categories: dict[str, str] = {}

    for label, description in raw_categories.items():
        if not isinstance(label, str) or not isinstance(description, str):
            raise ValueError(
                "LLM returned invalid categories. Category labels and "
                "descriptions must be strings."
            )
        validated_categories[label] = description

    return validated_categories


def parse_formatting_rule(response_json: dict[str, Any]) -> str | None:
    """
    Validate proposed formatting rule returned by the LLM.

    Parameters
    ----------
    response_json : dict[str, Any]
        Parsed LLM response.

    Returns
    -------
    str | None
        Validated formatting rule or ``None``.

    Raises
    ------
    ValueError
        If the formatting rule structure is invalid.
    """
    raw_rule = response_json.get("formatting_rule")

    if raw_rule is None:
        return None

    if not isinstance(raw_rule, str):
        raise ValueError("LLM returned invalid formatting_rule. Expected a string.")

    return raw_rule


def classify_attribute(
    llm: LLMClient,
    attribute_value_set: AttributeValueSet,
    debug_settings: DebugSettings,
) -> NormalizationDecision:
    """
    Ask the LLM to assign a normalization class to one attribute.

    Parameters
    ----------
    llm : LLMClient
        LLM client used for the decision.
    attribute_value_set : AttributeValueSet
        Aggregated values for one attribute.
    debug_settings : DebugSettings
        Settings controlling optional debug output.

    Returns
    -------
    NormalizationDecision
        Assigned normalization class for the attribute.
    """
    if attribute_value_set.total_value_count == 0:
        return NormalizationDecision(
            attribute_name=attribute_value_set.attribute_name,
            cardinality=attribute_value_set.cardinality,
            normalization_class="not_standardizable",
        )

    messages = build_messages(attribute_value_set)
    if debug_settings.print_prompts:
        logger.debug(
            "PROMPT for %s\n%s",
            attribute_value_set.attribute_name,
            json.dumps(messages, ensure_ascii=False, indent=2),
        )

    raw_response = llm.chat(messages)
    if debug_settings.print_outputs:
        logger.debug(
            "OUTPUT for %s\n%s", attribute_value_set.attribute_name, raw_response
        )

    response_json = get_json_from_noisy_json(raw_response)
    normalization_class = parse_normalization_class(response_json)
    categories = parse_categories(response_json)
    formatting_rule = parse_formatting_rule(response_json)

    if normalization_class == "standardizable_by_category":
        if not categories:
            raise ValueError(
                'LLM must return categories for "standardizable_by_category".'
            )
        formatting_rule = None
    elif normalization_class == "standardizable_by_format":
        if formatting_rule is None or formatting_rule.strip() == "":
            raise ValueError(
                'LLM must return formatting_rule for "standardizable_by_format".'
            )
        categories = None
    else:
        categories = None
        formatting_rule = None

    logger.info(
        "Processed attribute %s: %s",
        attribute_value_set.attribute_name,
        normalization_class,
    )
    return NormalizationDecision(
        attribute_name=attribute_value_set.attribute_name,
        cardinality=attribute_value_set.cardinality,
        normalization_class=normalization_class,
        categories=categories,
        formatting_rule=formatting_rule,
    )


def run_semantic_normalizer(
    dataframe: pd.DataFrame,
    llm_settings: LLMSettings,
    max_sampled_values: int,
    single_cardinality_threshold: float,
    debug_settings: DebugSettings,
) -> list[NormalizationDecision]:
    """
    Run semantic normalization classification for all attributes.

    Parameters
    ----------
    dataframe : pd.DataFrame
        Input dataframe with extracted spans.
    llm_settings : LLMSettings
        Settings used to construct the LLM client.
    max_sampled_values : int
        Maximum number of most frequent values shown to the LLM.
    single_cardinality_threshold : float
        Minimum share of non-empty sentences in which the attribute
        appears only once to classify it as ``single``.
    debug_settings : DebugSettings
        Settings controlling optional debug output.

    Returns
    -------
    list[NormalizationDecision]
        Normalization decisions for all attributes.
    """
    llm = get_llm(
        provider=llm_settings.provider,
        model=llm_settings.model,
        temperature=llm_settings.temperature,
        reasoning=llm_settings.reasoning,
    )
    attribute_value_sets = collect_attribute_values(
        dataframe=dataframe,
        max_sampled_values=max_sampled_values,
        single_cardinality_threshold=single_cardinality_threshold,
    )
    decisions: list[NormalizationDecision] = []

    for attribute_value_set in attribute_value_sets:
        decisions.append(
            classify_attribute(
                llm=llm,
                attribute_value_set=attribute_value_set,
                debug_settings=debug_settings,
            )
        )

    return decisions


def build_enriched_attribute_schema(
    attribute_schema: dict[str, dict[str, Any]],
    decisions: list[NormalizationDecision],
) -> dict[str, dict[str, Any]]:
    """
    Merge normalization decisions into the main attribute schema.

    Parameters
    ----------
    attribute_schema : dict[str, dict[str, Any]]
        Existing attribute schema.
    decisions : list[NormalizationDecision]
        Normalization decisions for all attributes.

    Returns
    -------
    dict[str, dict[str, Any]]
        Enriched attribute schema keyed by attribute name.
    """
    enriched_schema = {
        attribute_name: dict(attribute_details)
        for attribute_name, attribute_details in attribute_schema.items()
    }

    for decision in decisions:
        if decision.attribute_name not in enriched_schema:
            raise ValueError(
                "Normalization decision references an attribute missing from "
                f'the input schema: "{decision.attribute_name}".'
            )

        attribute_details = dict(enriched_schema[decision.attribute_name])
        attribute_details["cardinality"] = decision.cardinality
        attribute_details.pop("categories", None)
        attribute_details.pop("format", None)

        if decision.normalization_class == "standardizable_by_category":
            if decision.categories is not None:
                attribute_details["categories"] = decision.categories
        elif decision.normalization_class == "standardizable_by_format":
            if decision.formatting_rule is not None:
                attribute_details["format"] = decision.formatting_rule

        enriched_schema[decision.attribute_name] = attribute_details

    return enriched_schema


if __name__ == "__main__":
    args = __get_args__()
    setup_logging(
        args.verbose,
        args.log_file,
        force_debug=args.print_prompts or args.print_outputs,
    )

    dataframe = load_input_data(args.input)
    attribute_schema = validate_attribute_schema(load_json_file(args.attribute_schema))
    llm_settings = LLMSettings(
        provider=args.provider,
        model=args.model,
        temperature=args.temperature,
        reasoning=args.reasoning,
    )
    debug_settings = DebugSettings(
        print_prompts=args.print_prompts,
        print_outputs=args.print_outputs,
    )
    decisions = run_semantic_normalizer(
        dataframe=dataframe,
        llm_settings=llm_settings,
        max_sampled_values=args.max_sampled_values,
        single_cardinality_threshold=args.single_cardinality_threshold,
        debug_settings=debug_settings,
    )
    enriched_attribute_schema = build_enriched_attribute_schema(
        attribute_schema=attribute_schema,
        decisions=decisions,
    )

    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(
            enriched_attribute_schema,
            file,
            indent=2,
            ensure_ascii=False,
        )

    logger.info("Enriched attribute schema saved to %s", args.output)
