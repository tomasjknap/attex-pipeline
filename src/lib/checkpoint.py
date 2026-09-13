import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True, slots=True)
class CheckpointPaths:
    """
    File paths used by one checkpoint store.
    """

    base_path: str
    state_path: str
    records_path: str


@dataclass(frozen=True, slots=True)
class CheckpointState:
    """
    Persisted checkpoint state for resumable batch processing.
    """

    processed_item_ids: frozenset[str]
    metadata: dict[str, Any]


def build_checkpoint_paths(base_path: str) -> CheckpointPaths:
    """
    Build concrete file paths for a checkpoint store.

    Parameters
    ----------
    base_path : str
        Base path prefix for the checkpoint store.

    Returns
    -------
    CheckpointPaths
        Paths for the state JSON and records JSONL files.
    """
    return CheckpointPaths(
        base_path=base_path,
        state_path=f"{base_path}.state.json",
        records_path=f"{base_path}.records.jsonl",
    )


def build_default_checkpoint_base_path(output_path: str) -> str:
    """
    Build the default checkpoint base path for an output file.

    Parameters
    ----------
    output_path : str
        Path to the output file.

    Returns
    -------
    str
        Default checkpoint base path.
    """
    output_file = Path(output_path)
    return str(output_file.with_name(f"{output_file.name}.checkpoint"))


def load_checkpoint_state(base_path: str) -> CheckpointState:
    """
    Load checkpoint state from disk.

    Parameters
    ----------
    base_path : str
        Base path prefix for the checkpoint store.

    Returns
    -------
    CheckpointState
        Loaded state, or an empty state when the file does not exist.
    """
    checkpoint_paths = build_checkpoint_paths(base_path)
    state_file = Path(checkpoint_paths.state_path)

    if not state_file.exists():
        return CheckpointState(
            processed_item_ids=frozenset(),
            metadata={},
        )

    state_payload = json.loads(state_file.read_text(encoding="utf-8"))
    processed_item_ids = frozenset(
        str(item_id) for item_id in state_payload.get("processed_item_ids", [])
    )
    metadata = dict(state_payload.get("metadata", {}))
    return CheckpointState(
        processed_item_ids=processed_item_ids,
        metadata=metadata,
    )


def save_checkpoint_state(
    base_path: str,
    checkpoint_state: CheckpointState,
) -> None:
    """
    Persist checkpoint state atomically.

    Parameters
    ----------
    base_path : str
        Base path prefix for the checkpoint store.
    checkpoint_state : CheckpointState
        State that should be written to disk.
    """
    checkpoint_paths = build_checkpoint_paths(base_path)
    state_file = Path(checkpoint_paths.state_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = state_file.with_suffix(f"{state_file.suffix}.tmp")

    state_payload = {
        "processed_item_ids": sorted(checkpoint_state.processed_item_ids),
        "metadata": checkpoint_state.metadata,
    }
    temporary_file.write_text(
        json.dumps(state_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_file.replace(state_file)


def append_checkpoint_records(
    base_path: str,
    records: list[dict[str, Any]],
) -> None:
    """
    Append checkpoint records to the JSONL file.

    Parameters
    ----------
    base_path : str
        Base path prefix for the checkpoint store.
    records : list[dict[str, Any]]
        Records that should be appended.
    """
    if not records:
        return

    checkpoint_paths = build_checkpoint_paths(base_path)
    records_file = Path(checkpoint_paths.records_path)
    records_file.parent.mkdir(parents=True, exist_ok=True)

    with records_file.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")


def iter_checkpoint_records(base_path: str) -> Iterator[dict[str, Any]]:
    """
    Iterate over checkpoint records stored in JSONL format.

    Parameters
    ----------
    base_path : str
        Base path prefix for the checkpoint store.

    Yields
    ------
    dict[str, Any]
        One stored checkpoint record.
    """
    checkpoint_paths = build_checkpoint_paths(base_path)
    records_file = Path(checkpoint_paths.records_path)

    if not records_file.exists():
        return

    with records_file.open("r", encoding="utf-8") as file:
        for line in file:
            stripped_line = line.strip()
            if stripped_line == "":
                continue
            yield json.loads(stripped_line)


def load_processed_item_ids_from_records(
    base_path: str,
    item_id_key: str = "item_id",
) -> set[str]:
    """
    Reconstruct processed item IDs from stored checkpoint records.

    Parameters
    ----------
    base_path : str
        Base path prefix for the checkpoint store.
    item_id_key : str, default="item_id"
        Record key containing the processed item identifier.

    Returns
    -------
    set[str]
        Processed item IDs discovered in the records file.
    """
    processed_item_ids: set[str] = set()

    for record in iter_checkpoint_records(base_path):
        item_id = record.get(item_id_key)
        if item_id is not None:
            processed_item_ids.add(str(item_id))

    return processed_item_ids
