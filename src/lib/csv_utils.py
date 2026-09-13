import csv

import pandas as pd
from pandas.errors import ParserError


def detect_csv_delimiter(file_path: str) -> str:
    """
    Detect whether a CSV file uses a comma or semicolon delimiter.

    Parameters
    ----------
    file_path : str
        Path to the CSV file.

    Returns
    -------
    str
        Detected delimiter, either `","` or `";"`.
    """
    with open(file_path, "r", encoding="utf-8", newline="") as file:
        sample = file.read(4096)

    if not sample:
        return ","

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        return str(dialect.delimiter)
    except csv.Error:
        comma_count = sample.count(",")
        semicolon_count = sample.count(";")
        return ";" if semicolon_count > comma_count else ","


def load_csv_file(file_path: str, **read_csv_kwargs: object) -> pd.DataFrame:
    """
    Load a CSV file after detecting whether it uses `,` or `;`.

    Parameters
    ----------
    file_path : str
        Path to the CSV file.
    **read_csv_kwargs : object
        Additional keyword arguments forwarded to ``pandas.read_csv``.

    Returns
    -------
    pd.DataFrame
        Parsed CSV data.
    """
    delimiter = detect_csv_delimiter(file_path)

    try:
        return pd.read_csv(file_path, sep=delimiter, **read_csv_kwargs)
    except ParserError:
        alternate_delimiter = ";" if delimiter == "," else ","
        return pd.read_csv(
            file_path,
            sep=alternate_delimiter,
            **read_csv_kwargs,
        )
