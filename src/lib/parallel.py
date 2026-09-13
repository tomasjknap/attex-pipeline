from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeVar


TaskPayload = TypeVar("TaskPayload")
TaskResult = TypeVar("TaskResult")


@dataclass(frozen=True, slots=True)
class ParallelTask:
    """
    Task metadata for parallel execution.
    """

    case_id: Any
    payload: Any


@dataclass(frozen=True, slots=True)
class ParallelTaskFailure:
    """
    Failure details for a parallel task.
    """

    task: ParallelTask
    error: Exception


def run_parallel_tasks(
    tasks: list[ParallelTask],
    worker: Callable[[Any], TaskResult],
    on_failure: Literal["raise", "collect"],
) -> tuple[list[tuple[ParallelTask, TaskResult]], list[ParallelTaskFailure]]:
    """
    Run tasks in parallel and collect their results.

    Parameters
    ----------
    tasks : list[ParallelTask]
        Tasks to execute in parallel.
    worker : Callable[[Any], TaskResult]
        Function called with each task payload.
    on_failure : Literal["raise", "collect"]
        Whether to raise immediately on a task failure or collect failures.

    Returns
    -------
    tuple[list[tuple[ParallelTask, TaskResult]], list[ParallelTaskFailure]]
        Successful results paired with task metadata and collected failures.

    Raises
    ------
    RuntimeError
        If ``on_failure`` is ``"raise"`` and any task fails.
    """
    if not tasks:
        return [], []

    successful_results: list[tuple[ParallelTask, TaskResult]] = []
    failures: list[tuple[int, ParallelTaskFailure]] = []

    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        future_to_task: dict[Future[TaskResult], tuple[int, ParallelTask]] = {}

        for sequence_index, task in enumerate(tasks):
            future = executor.submit(worker, task.payload)
            future_to_task[future] = (sequence_index, task)

        for future in as_completed(future_to_task):
            sequence_index, task = future_to_task[future]
            try:
                successful_results.append((task, future.result(), sequence_index))
            except Exception as error:
                if on_failure == "raise":
                    raise RuntimeError(
                        f"Failed to process case {task.case_id}: {error}"
                    ) from error
                failures.append((
                    sequence_index,
                    ParallelTaskFailure(
                        task=task,
                        error=error,
                    ),
                ))

    successful_results.sort(key=lambda item: item[2])
    failures.sort(key=lambda item: item[0])
    return [(task, result) for task, result, _ in successful_results], [
        failure for _, failure in failures
    ]
