#!/usr/bin/env python3
import argparse
import csv
import json
import sys
from textwrap import dedent
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

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


def __get_args__() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract attribute schema from factual"
            " statements using iterative LLM exploration"
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
        "--category",
        "-c",
        required=False,
        help=("Value of judgement_model_short column to filter on"),
    )
    parser.add_argument(
        "--initial-attributes",
        "-a",
        required=True,
        help="JSON file with nested initial attribute schema",
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
        "--parallel-batch-size",
        "-b",
        type=int,
        default=10,
        help=("Number of statements to process in parallel at once (default: 10)"),
    )
    parser.add_argument(
        "--schema-update-batch-size",
        type=int,
        default=10,
        help=(
            "Minimum number of newly processed statements"
            " before inducing new attributes"
            " (default: 10)"
        ),
    )
    parser.add_argument(
        "--sample",
        "-s",
        type=int,
        default=None,
        help=("Limit to first N statements (default: all)"),
    )
    parser.add_argument(
        "--population-threshold",
        type=float,
        default=0.85,
        help=(
            "Maximum missing-value ratio for accepting a new attribute (default: 0.85)"
        ),
    )
    add_logging_args(parser)
    return parser.parse_args()


def induce_new_attributes(
    llm: LLMClient,
    residuals: Dict[Any, str],
    attribute_list: Dict[str, Any],
) -> Dict[str, Dict[str, str]]:
    """Discover new attributes from residual texts."""
    prompt_attribute_list = {
        attribute_name: attribute_details["description"]
        for attribute_name, attribute_details in attribute_list.items()
    }
    system_prompt = dedent(
        f"""\
        These are the residual texts from court verdicts after extracting the following attributes:
        {prompt_attribute_list}

        What other pieces of information do you see repeatedly in the residual texts?
        Return a JSON with the emergent attribute names as keys and descriptions as values.
        The attributes should be as granular as possible, but do not repeat the attributes that were already defined."""
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": str(residuals)},
    ]

    response = llm.chat(messages)
    result = get_json_from_noisy_json(response)
    structured_result = {
        attribute_name: {"description": description}
        for attribute_name, description in result.items()
    }
    validated_result = normalize_attribute_schema(structured_result)
    logger.debug("Candidate attributes: %s", validated_result)
    return validated_result


def normalize_attribute_schema(
    attribute_schema: Dict[str, Any],
) -> Dict[str, Dict[str, str]]:
    """
    Normalize attribute schema with nested objects and descriptions.

    Parameters
    ----------
    attribute_schema : Dict[str, Any]
        Attribute schema to normalize.

    Returns
    -------
    Dict[str, Dict[str, str]]
        Validated attribute schema.

    Raises
    ------
    ValueError
        If the schema has an unsupported shape.
    """
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

    return attribute_schema


def populate_new_attributes(
    llm: LLMClient,
    case_id: Any,
    sentence: str,
    attribute_list: Dict[str, Any],
    attributes_structured: Dict[Any, Dict[str, Any]],
    residuals: Dict[Any, str],
) -> None:
    """Extract attribute values and residual from a sentence."""
    prompt_template = load_prompt_template_by_name("attribute_extraction_prompt")
    system_prompt = render_prompt_template(
        prompt_template,
        {
            "attribute_schema": format_attribute_schema(attribute_list),
        },
    )

    extraction_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": sentence},
    ]
    extraction_response = llm.chat(extraction_messages)
    new_attributes = get_json_from_noisy_json(extraction_response)

    attributes_structured[case_id].update(new_attributes)

    residual_instruction = dedent(
        """\
        What other information was there in the statement but is not covered by the attributes?
        Write one sentence containing the extra information.
        Output a JSON with one attribute: "residual" where the value is the sentence with extra information.
        Only output information from the original text.
        The sentence must be in the original language - Slovak.
        If there is no extra information, output {"residual": "n/a"}."""
    )

    residual_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": sentence},
        {
            "role": "assistant",
            "content": str(new_attributes),
        },
        {
            "role": "user",
            "content": residual_instruction,
        },
    ]
    residual_response = llm.chat(residual_messages)
    residual_json = get_json_from_noisy_json(residual_response)

    residual_value = residual_json.get("residual", "n/a")
    attributes_structured[case_id]["residual"] = residual_value
    residuals[case_id] = residual_value

    logger.info("Processed case %s", case_id)
    logger.debug("%s", {**new_attributes, "residual": residual_value})


def check_population(
    attributes_structured: Dict[Any, Dict[str, Any]],
    candidate_attributes: Dict[str, Dict[str, str]],
    threshold: float = 0.85,
) -> Dict[str, Dict[str, str]]:
    """Filter candidate attributes by population rate."""
    if not candidate_attributes:
        return {}

    df = pd.DataFrame.from_dict(attributes_structured, orient="index").reset_index()
    df.replace("n/a", np.nan, inplace=True)

    missing_ratio = df.isna().sum() / len(df)
    final_attributes = {}

    for attribute, description in candidate_attributes.items():
        if attribute not in df.columns:
            logger.info(
                "Dropping attribute: %s (not present in extracted data)", attribute
            )
            continue

        if missing_ratio[attribute] <= threshold:
            final_attributes[attribute] = description
            logger.info("New attribute accepted: %s", attribute)
        else:
            logger.info("Dropping attribute: %s", attribute)

    return final_attributes


def run_parallel_population(
    llm: LLMClient,
    tasks: list[tuple[Any, str, Dict[str, Any]]],
    attributes_structured: Dict[Any, Dict[str, Any]],
    residuals: Dict[Any, str],
) -> None:
    """
    Populate attributes for multiple cases in parallel.

    Parameters
    ----------
    llm : LLMClient
        LLM client used for extraction.
    tasks : list[tuple[Any, str, Dict[str, Any]]]
        Tuples of case id, sentence, and attribute schema to use.
    attributes_structured : Dict[Any, Dict[str, Any]]
        Mutable store for extracted attributes.
    residuals : Dict[Any, str]
        Mutable store for residual texts.
    """
    if not tasks:
        return

    parallel_tasks = [
        ParallelTask(
            case_id=case_id,
            payload=(case_id, sentence, attribute_list),
        )
        for case_id, sentence, attribute_list in tasks
    ]

    run_parallel_tasks(
        tasks=parallel_tasks,
        worker=lambda task_payload: populate_new_attributes(
            llm,
            task_payload[0],
            task_payload[1],
            task_payload[2],
            attributes_structured,
            residuals,
        ),
        on_failure="raise",
    )


def update_schema_from_residuals(
    llm: LLMClient,
    attribute_list: Dict[str, Any],
    attributes_structured: Dict[Any, Dict[str, Any]],
    residuals: Dict[Any, str],
    population_threshold: float,
) -> Dict[str, Any]:
    """
    Induce and apply new attributes from accumulated residuals.

    Parameters
    ----------
    llm : LLMClient
        LLM client used for attribute induction.
    attribute_list : Dict[str, Any]
        Current attribute schema.
    attributes_structured : Dict[Any, Dict[str, Any]]
        Mutable store for extracted attributes.
    residuals : Dict[Any, str]
        Mutable store for residual texts.
    population_threshold : float
        Maximum missing-value ratio for accepting a new attribute.

    Returns
    -------
    Dict[str, Any]
        Updated attribute schema.
    """
    candidate_attributes = induce_new_attributes(
        llm,
        residuals,
        attribute_list,
    )

    residual_tasks: list[tuple[Any, str, Dict[str, Any]]] = []

    for existing_case_id, case_data in attributes_structured.items():
        residual = case_data.get("residual", "n/a")
        if residual != "n/a":
            residual_tasks.append((existing_case_id, residual, candidate_attributes))

    run_parallel_population(
        llm=llm,
        tasks=residual_tasks,
        attributes_structured=attributes_structured,
        residuals=residuals,
    )

    new_attributes = check_population(
        attributes_structured,
        candidate_attributes,
        threshold=population_threshold,
    )
    attribute_list.update(new_attributes)
    return attribute_list


def run_exploration(
    df: pd.DataFrame,
    llm: LLMClient,
    initial_attributes: Dict[str, Any],
    parallel_batch_size: int,
    schema_update_batch_size: int,
    population_threshold: float,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Run iterative attribute exploration."""
    attributes_structured: Dict[Any, Dict[str, Any]] = {}
    residuals: Dict[Any, str] = {}
    attribute_list = dict(initial_attributes)
    rows = [row for _, row in df.iterrows()]
    processed_since_schema_update = 0

    for batch_start in range(0, len(rows), parallel_batch_size):
        batch_rows = rows[batch_start : batch_start + parallel_batch_size]
        batch_end = batch_start + len(batch_rows) - 1
        logger.info("Processing rows %d to %d", batch_start, batch_end)

        initial_tasks: list[tuple[Any, str, Dict[str, Any]]] = []

        for row in batch_rows:
            case_id = row["judgement_slt_id"]
            sentence = row["judgement_factual_sentence"]
            attributes_structured[case_id] = {
                "sentence": sentence,
            }
            initial_tasks.append((case_id, sentence, attribute_list))

        run_parallel_population(
            llm=llm,
            tasks=initial_tasks,
            attributes_structured=attributes_structured,
            residuals=residuals,
        )
        processed_since_schema_update += len(batch_rows)

        if processed_since_schema_update >= schema_update_batch_size:
            attribute_list = update_schema_from_residuals(
                llm=llm,
                attribute_list=attribute_list,
                attributes_structured=attributes_structured,
                residuals=residuals,
                population_threshold=population_threshold,
            )
            processed_since_schema_update = 0

    if processed_since_schema_update > 0:
        attribute_list = update_schema_from_residuals(
            llm=llm,
            attribute_list=attribute_list,
            attributes_structured=attributes_structured,
            residuals=residuals,
            population_threshold=population_threshold,
        )

    result_df = pd.DataFrame.from_dict(
        attributes_structured, orient="index"
    ).reset_index()
    return result_df, attribute_list


def load_input_data(
    path: str,
    category: str,
    sample: int | None = None,
) -> pd.DataFrame:
    """Load and filter input CSV data."""
    csv.field_size_limit(sys.maxsize)

    df = load_csv_file(
        path,
        quoting=csv.QUOTE_ALL,
        quotechar='"',
        escapechar="\\",
        engine="python",
    )

    if "judgement_model_short" in df and category:
        filtered = df[df["judgement_model_short"] == category]
    else:
        filtered = df

    if sample is not None:
        filtered = filtered.head(sample)

    return pd.DataFrame(filtered)


def load_initial_attributes(path: str) -> Dict[str, Any]:
    """Load nested initial attribute schema from JSON."""
    with open(path, "r", encoding="utf-8") as file:
        initial_attributes = json.load(file)

    if not isinstance(initial_attributes, dict):
        raise ValueError("Initial attributes must be a JSON object.")

    return normalize_attribute_schema(initial_attributes)


if __name__ == "__main__":
    args = __get_args__()
    setup_logging(args.verbose, args.log_file)

    initial_attributes = load_initial_attributes(args.initial_attributes)

    df = load_input_data(args.input, args.category, args.sample)

    llm = get_llm(
        provider=args.provider,
        model=args.model,
        temperature=args.temperature,
        reasoning=args.reasoning,
    )

    df_attributes, attribute_list = run_exploration(
        df=df,
        llm=llm,
        initial_attributes=initial_attributes,
        parallel_batch_size=args.parallel_batch_size,
        schema_update_batch_size=args.schema_update_batch_size,
        population_threshold=args.population_threshold,
    )

    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(attribute_list, file, indent=2, ensure_ascii=False)

    logger.info("Attribute list saved to %s", args.output)
    logger.debug("Final attributes: %s", attribute_list)
