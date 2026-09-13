#!/usr/bin/env python3
"""
Centralised logging setup for ATTEX pipeline stages.

All stage apps (a_–h_) should call ``setup_logging`` once from their
``__main__`` block and take their module logger from ``get_logger``.
Logs are routed to ``stderr`` via ``rich`` so that ``stdout`` stays a
clean data channel for stage-to-stage piping.
"""

import argparse
import logging
from typing import Final

from rich.console import Console
from rich.logging import RichHandler

_VERBOSITY_TO_LEVEL: Final[dict[int, int]] = {
    0: logging.WARNING,
    1: logging.INFO,
}
_FILE_FORMAT: Final[str] = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    """
    Return the module logger to emit ATTEX records through.

    Parameters
    ----------
    name : str
        The emitting module's ``__name__``.

    Returns
    -------
    logging.Logger
        A named logger whose records reach the handlers installed by
        ``setup_logging``.

    Notes
    -----
    This is the standard-library ``logging.getLogger`` under a project
    name, so that modules take their whole logging surface from this
    module and never configure logging themselves.
    """
    return logging.getLogger(name)


def add_logging_args(parser: argparse.ArgumentParser) -> None:
    """
    Register the shared ``-v/--verbose`` and ``--log-file`` CLI options.

    Stage apps call this from their ``__get_args__`` so the logging CLI
    surface stays identical across the pipeline; feed the resulting
    ``args.verbose`` and ``args.log_file`` into ``setup_logging``.
    """
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity: -v shows progress, -vv shows debug details.",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Append plain-formatted logs to this file in addition to stderr.",
    )


def setup_logging(
    verbosity: int = 0, log_file: str | None = None, force_debug: bool = False
) -> None:
    """
    Configure the root logger for an ATTEX stage app.

    Parameters
    ----------
    verbosity : int, default 0
        Maps to a log level: ``0`` → WARNING, ``1`` → INFO, ``>=2`` → DEBUG.
        Wire this to ``argparse``'s ``action="count"`` (``-v``, ``-vv``).
    log_file : str or None, default None
        If given, also append plain-formatted records to this file
        in addition to the rich ``stderr`` handler.
    force_debug : bool, default False
        Raise the effective verbosity to DEBUG regardless of ``verbosity``.
        Wire this to explicit debug opt-ins such as ``--print-outputs`` so
        they work without also requiring ``-vv``.

    Notes
    -----
    The pretty handler writes to ``stderr`` so that piped pipelines
    (``a_… | b_… | …``) keep ``stdout`` free for structured data.
    Any existing handlers on the root logger are cleared so that
    repeated calls in the same process are idempotent.
    """
    if force_debug:
        verbosity = max(verbosity, 2)
    level = _VERBOSITY_TO_LEVEL.get(verbosity, logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    root.addHandler(
        RichHandler(
            console=Console(stderr=True),
            show_path=False,
            rich_tracebacks=True,
            markup=True,
        )
    )

    if log_file is not None:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        root.addHandler(file_handler)
