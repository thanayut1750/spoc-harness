"""Explicit reset of the harness's managed state, never arbitrary host files."""

import asyncio
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from org_harness.autonomy import AutonomousCheckpointYield
from org_harness.config import Settings
from org_harness.storage import TERMINAL, ConflictError


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


async def regenesis(settings: Settings, storage: Any) -> dict:
    """Stop execution, erase managed run data, and restore environment defaults.

    Database infrastructure may itself live under data_dir, so only the named
    application-owned directories are removed. External workspaces and .env are
    never traversed. The caller serializes HTTP mutations during this operation.
    """
    for run in await storage.list_runs():
        if run["status"] not in TERMINAL:
            try:
                await storage.command(run["run_id"], "cancel", {})
            except ConflictError:
                pass  # A run may have completed while cancellation was requested.
    deadline = asyncio.get_running_loop().time() + 10
    while True:
        async with storage.worker_lock() as guard:
            if guard:
                from org_harness.tools import stop_run_command_processes

                for run in await storage.list_runs():
                    try:
                        await stop_run_command_processes(settings, run)
                    except AutonomousCheckpointYield as exc:
                        raise ConflictError(
                            "Command cleanup is still pending. Retry Regenesis after execution stops."
                        ) from exc
                root = settings.data_dir.resolve()
                root.mkdir(parents=True, exist_ok=True)
                trash = root / ".regenesis-trash"
                if trash.is_symlink():
                    trash.unlink()
                stage = trash / uuid4().hex
                stage.mkdir(parents=True)
                moved: list[tuple[Path, Path]] = []
                try:
                    for name in ("artifacts", "workspaces"):
                        source = root / name
                        if source.exists() or source.is_symlink():
                            target = stage / name
                            source.rename(target)
                            moved.append((source, target))
                    removed = await storage.reset_data()
                except BaseException:
                    for source, target in reversed(moved):
                        if target.exists() or target.is_symlink():
                            target.rename(source)
                    _remove(stage)
                    raise
                # Keep the worker guard until all retired file data is gone.
                await asyncio.to_thread(_remove, trash)
                for name in ("api.log", "worker.log"):
                    log = root / name
                    if log.is_file() and not log.is_symlink():
                        with log.open("r+b") as handle:
                            handle.truncate(0)
                return {
                    "status": "reset",
                    "removed_runs": removed,
                    "settings": settings.public_settings(),
                }
        if asyncio.get_running_loop().time() >= deadline:
            raise ConflictError(
                "Execution is still stopping. Retry Regenesis after the worker stops."
            )
        await asyncio.sleep(0.1)
