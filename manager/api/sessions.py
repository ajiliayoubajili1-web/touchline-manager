"""Multi-user session layer.

Every device gets its own save directory (hashed device id) so people on a
shared server play independently. The legacy "root" directory (no device id)
keeps top-level saves; for continuity, the first device to connect claims any
saves that exist there.

Frontends attach ``X-Device-Id`` on every request; without it, requests map to
the root/legacy user (kept for tests and local curl-style use).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from manager.api.service import GameService
from manager.save.files import DEFAULT_SAVE_DIR, SAVE_EXTENSION

LEGACY_USER = ""


def _hash_id(user_id: str) -> str:
    return hashlib.sha1(user_id.encode("utf-8")).hexdigest()[:12]


class SessionService:
    """Resolve a device id to a GameService scoped to that user's saves."""

    def __init__(self, save_root=None, legacy=None):
        if save_root is None and legacy is not None and legacy.save_dir is not None:
            save_root = legacy.save_dir
        self.save_root = Path(save_root) if save_root else DEFAULT_SAVE_DIR
        self._services: dict[str, GameService] = {}
        if legacy is not None:
            self._services[LEGACY_USER] = legacy

    def service_for(self, user_id: str | None) -> GameService:
        user_id = (user_id or "").strip()
        svc = self._services.get(user_id)
        if svc is None:
            svc = GameService(save_dir=self._dir_for(user_id))
            self._services[user_id] = svc
        return svc

    def _dir_for(self, user_id: str) -> Path:
        if not user_id:
            return self.save_root
        user_dir = self.save_root / _hash_id(user_id)
        if not user_dir.exists():
            user_dir.mkdir(parents=True, exist_ok=True)
            self._claim_legacy(user_dir)
        return user_dir

    def _claim_legacy(self, user_dir: Path) -> None:
        claim_file = self.save_root / ".claim.json"
        legacy_files = sorted(self.save_root.glob(f"*{SAVE_EXTENSION}"))
        if not legacy_files or claim_file.exists():
            return
        try:
            claim_file.write_text(
                json.dumps({"claimed_by": user_dir.name}), encoding="utf-8"
            )
            for path in legacy_files:
                shutil.move(str(path), user_dir / path.name)
        except OSError:
            pass