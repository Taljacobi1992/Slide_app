import copy
from datetime import datetime
from config import MAX_REVISIONS


class RevisionManager:

    def __init__(self):
        self.revisions = []
        self.current_revision_id = 0

    def save_revision(self, skeleton: dict, action: str, description: str) -> int:
        self.current_revision_id += 1
        revision = {
            "revision_id": self.current_revision_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "description": description,
            "snapshot": copy.deepcopy(skeleton)
        }
        self.revisions.append(revision)
        if len(self.revisions) > MAX_REVISIONS:
            self.revisions = [self.revisions[0]] + self.revisions[-(MAX_REVISIONS - 1):]
        return self.current_revision_id

    def get_revision(self, revision_id: int) -> dict | None:
        for rev in self.revisions:
            if rev["revision_id"] == revision_id:
                return rev
        return None

    def restore_revision(self, revision_id: int) -> dict | None:
        rev = self.get_revision(revision_id)
        if rev is None:
            return None
        return copy.deepcopy(rev["snapshot"])

    def get_revision_choices(self) -> list[str]:
        choices = []
        for rev in reversed(self.revisions):
            rid = rev["revision_id"]
            ts = rev["timestamp"]
            action = rev["action"]
            desc = rev["description"]
            choices.append(f"[גרסה {rid}] {ts} — {action}: {desc}")
        return choices

    def get_latest_id(self) -> int:
        return self.current_revision_id

    def reset(self):
        self.revisions = []
        self.current_revision_id = 0