"""Revision manager — stores and restores deck snapshots."""

import copy
from datetime import datetime
from typing import Optional
from config import settings


class RevisionManager:
    """Manages a capped history of deck revisions with snapshot/restore."""

    def __init__(self) -> None:
        self.revisions: list[dict] = []
        self.current_revision_id: int = 0

    def save_revision(self, skeleton: dict, action: str, description: str) -> int:
        """Save a deep-copy snapshot of the skeleton and return the new revision id."""
        self.current_revision_id += 1
        revision: dict = {
            "revision_id": self.current_revision_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "description": description,
            "snapshot": copy.deepcopy(skeleton),
        }
        self.revisions.append(revision)
        if len(self.revisions) > settings.settings.max_revisions:
            self.revisions = [self.revisions[0]] + self.revisions[-(settings.settings.max_revisions - 1):]
        return self.current_revision_id

    def get_revision(self, revision_id: int) -> Optional[dict]:
        """Return the revision dict for a given id, or None."""
        for rev in self.revisions:
            if rev["revision_id"] == revision_id:
                return rev
        return None

    def restore_revision(self, revision_id: int) -> Optional[dict]:
        """Return a deep copy of the skeleton at a given revision, or None."""
        rev: Optional[dict] = self.get_revision(revision_id)
        if rev is None:
            return None
        return copy.deepcopy(rev["snapshot"])

    def get_revision_choices(self) -> list[str]:
        """Build a list of human-readable revision labels for UI dropdowns."""
        choices: list[str] = []
        for rev in reversed(self.revisions):
            rid: int = rev["revision_id"]
            ts: str = rev["timestamp"]
            action: str = rev["action"]
            desc: str = rev["description"]
            choices.append(f"[גרסה {rid}] {ts} — {action}: {desc}")
        return choices

    def get_latest_id(self) -> int:
        """Return the most recent revision id."""
        return self.current_revision_id

    def reset(self) -> None:
        """Clear all revisions and reset the counter."""
        self.revisions = []
        self.current_revision_id = 0
