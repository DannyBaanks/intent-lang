"""Transactional execution for filesystem effects."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .executor import execute_program
from .program import Program


def execute_transaction(program: Program, paths: list[str | Path]) -> dict:
    """Execute and restore tracked paths when the program fails.

    This is deliberately explicit: callers must list paths whose previous
    state they want protected. Unlisted external effects are not rolled back.
    """
    root = Path(tempfile.mkdtemp(prefix="intentlang-txn-"))
    snapshots: list[tuple[Path, Path | None]] = []
    try:
        for index, raw_path in enumerate(paths):
            path = Path(raw_path)
            backup = root / str(index)
            if path.exists():
                if path.is_dir():
                    shutil.copytree(path, backup)
                else:
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, backup)
                snapshots.append((path, backup))
            else:
                snapshots.append((path, None))
        result = execute_program(program)
        if result.get("status") != "OK":
            _restore(snapshots)
            result["transaction"] = "ROLLED_BACK"
        else:
            result["transaction"] = "COMMITTED"
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _restore(snapshots: list[tuple[Path, Path | None]]) -> None:
    for path, backup in reversed(snapshots):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        if backup is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            if backup.is_dir():
                shutil.copytree(backup, path)
            else:
                shutil.copy2(backup, path)
