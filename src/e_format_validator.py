#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import asdict
from os import path

import pandas as pd
from pandas import DataFrame
from rich.console import Console
from rich.progress import track

from lib.data.variable_constraint import variable_factory
from lib.logging import add_logging_args, get_logger, setup_logging

logger = get_logger(__name__)
_stderr_console = Console(stderr=True)


def __get_args__() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Format validator which validates datasets using predefined constraints"
    )
    parser.add_argument(
        "dataset_file_path",
        type=str,
        default="/dev/stdin",
        help="Path to the CSV file to validate.",
    )
    parser.add_argument(
        "--constraints", type=str, help="Path to directory with constraints yaml file."
    )
    parser.add_argument("--variable", type=str, help="Variable to validate.")
    add_logging_args(parser)
    parser.add_argument(
        "--report",
        type=str,
        default=None,
        help="Write one JSON record per Violation to this JSONL file.",
    )
    return parser.parse_args()


def get_dataset(file_path: str, variable_name: str) -> DataFrame:
    """
    Read the dataset and return a single-column DataFrame.

    Parameters
    ----------
    file_path : str
        Path to the CSV file to read.
    variable_name : str
        Name of the column to load from the CSV file.

    Returns
    -------
    DataFrame
        A DataFrame containing only the requested column.

    Raises
    ------
    KeyError
        If ``variable_name`` is not a column in the CSV at ``file_path``.
    """
    try:
        return pd.read_csv(file_path, usecols=[variable_name])
    except ValueError as exc:
        raise KeyError(
            f"variable {variable_name!r} not found in dataset {file_path!r}"
        ) from exc


def main(
    dataset: pd.DataFrame,
    variable_name: str,
    constraint_file_path: str,
    report_path: str | None = None,
) -> tuple[int, int]:
    """
    Validate the dataset using the provided constraints.

    Parameters
    ----------
    dataset : pd.DataFrame
        A DataFrame containing one column with the variable to validate.
    variable_name : str
        Name of the column in ``dataset`` to validate.
    constraint_file_path : str
        Path to the YAML file containing the constraints for validation.
    report_path : str or None, default None
        If given, append each ``Violation`` as a JSON record (one per
        line) to this file.

    Returns
    -------
    tuple of (int, int)
        Counts of valid and invalid rows respectively.
    """
    count_valid = 0
    count_invalid = 0

    report_file = open(report_path, "w") if report_path is not None else None
    try:
        for _, row in track(
            dataset.iterrows(),
            description="Validating",
            console=_stderr_console,
        ):
            raw_value = row[variable_name]
            v = variable_factory(raw_value, constraint_file_path)
            ok = v.validate()
            for violation in v.violations:
                log = logger.error if violation.severity == "error" else logger.warning
                log(
                    "[bold]%s[/bold] [yellow]%s[/yellow]: %s | value=%r",
                    violation.type,
                    violation.name,
                    violation.message,
                    violation.value,
                )
                if report_file is not None:
                    json.dump(
                        asdict(violation),
                        report_file,
                        ensure_ascii=False,
                        default=str,
                    )
                    report_file.write("\n")
            if ok:
                count_valid += 1
            else:
                count_invalid += 1
    finally:
        if report_file is not None:
            report_file.close()

    total = count_valid + count_invalid
    rate = (count_valid / total * 100) if total else 0.0
    logger.info("Validation completed")
    logger.info("Valid rows: %d", count_valid)
    logger.info("Invalid rows: %d", count_invalid)
    logger.info("Valid rate: %.2f%%", rate)
    return count_valid, count_invalid


if __name__ == "__main__":
    args = __get_args__()
    setup_logging(args.verbose, args.log_file)

    var_name = args.variable
    dataset_file_path = args.dataset_file_path
    constraints_path = path.join(args.constraints, f"{var_name}.yml")

    try:
        df = get_dataset(dataset_file_path, var_name)
    except KeyError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    main(df, var_name, constraints_path, args.report)
