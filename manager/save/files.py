"""Structured save/load for careers.

A whole career is one :class:`CareerState` graph, persisted as a single JSON
file. Loading reconstructs the exact objects via the generic serializer, so a
career can be continued across sessions and seasons.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from manager.core.models import CareerState
from manager.core.serialization import dump, load

DEFAULT_SAVE_DIR = Path(__file__).resolve().parent.parent.parent / "saves"
SAVE_EXTENSION = ".json"


class SaveError(Exception):
    pass


def save_path(career_id: str, save_dir: Path | None = None) -> Path:
    directory = save_dir or DEFAULT_SAVE_DIR
    return directory / f"{career_id}{SAVE_EXTENSION}"


def write_save(state: CareerState, save_dir: Path | None = None) -> Path:
    """Persist a career to disk as structured JSON."""
    path = save_path(state.career_id, save_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dump(state)
    payload["_meta"] = {"saved_at": _now(), "version": state.version}
    try:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        raise SaveError(f"could not write save file {path}: {exc}") from exc
    return path


def read_save(career_id: str, save_dir: Path | None = None) -> CareerState:
    """Load a career from disk."""
    path = save_path(career_id, save_dir)
    if not path.is_file():
        raise SaveError(f"no save found for career {career_id!r}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SaveError(f"could not read save file {path}: {exc}") from exc
    payload.pop("_meta", None)
    return load(CareerState, payload)


def delete_save(career_id: str, save_dir: Path | None = None) -> None:
    path = save_path(career_id, save_dir)
    if path.is_file():
        path.unlink()


def list_saves(save_dir: Path | None = None) -> list[dict]:
    """List save files with friendly metadata, newest first."""
    directory = save_dir or DEFAULT_SAVE_DIR
    if not directory.is_dir():
        return []
    entries = []
    for path in sorted(directory.glob(f"*{SAVE_EXTENSION}")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = payload.get("_meta", {})
        club_id = payload.get("user_club_id", "")
        club_name = (payload.get("clubs") or {}).get(club_id, {}).get("name", "Unknown")
        entries.append({
            "career_id": payload.get("career_id", ""),
            "title": payload.get("title", "Untitled career"),
            "club": club_name,
            "difficulty": payload.get("difficulty", ""),
            "season": payload.get("current_season", ""),
            "week": payload.get("current_week", 0),
            "saved_at": meta.get("saved_at", ""),
            "size_bytes": path.stat().st_size,
        })
    entries.sort(key=lambda e: e["saved_at"], reverse=True)
    return entries


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")