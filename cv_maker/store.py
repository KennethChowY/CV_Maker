"""File-backed memory store with history and undo.

Layout of the data directory:

    memory.json          current memory (source of truth)
    history.jsonl        one line per change: what you typed and what changed
    snapshots/*.json     memory as it was before each change (used for undo)
    cv.json              last generated CV (structured)
    cv.html              current CV body, including any manual edits
    cv_meta.json         when/for what the CV was generated, whether it was hand-edited
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .schema import CVDocument, Memory

_SECTIONS_WITH_IDS = ("experience", "education", "projects", "achievements")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def ensure_ids(memory: Memory) -> Memory:
    """Give every item a unique id so later updates can refer to it."""
    seen: set[str] = set()
    for section in _SECTIONS_WITH_IDS:
        for i, item in enumerate(getattr(memory, section)):
            base = re.sub(r"[^a-z0-9]+", "-", (item.id or "").lower()).strip("-") or f"{section[:3]}-{i + 1}"
            candidate, n = base, 2
            while candidate in seen:
                candidate, n = f"{base}-{n}", n + 1
            item.id = candidate
            seen.add(candidate)
    return memory


class Store:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        self.snapshots = self.dir / "snapshots"
        self.snapshots.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.dir / "memory.json"
        self.history_path = self.dir / "history.jsonl"
        self.cv_json_path = self.dir / "cv.json"
        self.cv_html_path = self.dir / "cv.html"
        self.cv_meta_path = self.dir / "cv_meta.json"
        self.settings_path = self.dir / "settings.json"

    # ---- memory -------------------------------------------------------

    def load_memory(self) -> Memory:
        if not self.memory_path.exists():
            return Memory()
        return Memory.model_validate_json(self.memory_path.read_text(encoding="utf-8"))

    def save_memory(self, memory: Memory, *, source: str, input_text: str = "", changes: list[str] | None = None) -> None:
        """Snapshot the current memory, write the new one, and log the change."""
        ensure_ids(memory)
        stamp = _now()
        if self.memory_path.exists():
            (self.snapshots / f"{stamp.replace(':', '-')}.json").write_text(
                self.memory_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        _write_atomic(self.memory_path, memory.model_dump_json(indent=2))
        entry = {"at": stamp, "source": source, "input": input_text, "changes": changes or []}
        with self.history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def history(self, limit: int = 50) -> list[dict]:
        if not self.history_path.exists():
            return []
        lines = self.history_path.read_text(encoding="utf-8").splitlines()
        entries = [json.loads(line) for line in lines if line.strip()]
        return list(reversed(entries))[:limit]

    def can_undo(self) -> bool:
        return any(self.snapshots.glob("*.json"))

    def undo(self) -> bool:
        """Restore the memory to how it was before the most recent change."""
        snaps = sorted(self.snapshots.glob("*.json"))
        if not snaps:
            return False
        latest = snaps[-1]
        _write_atomic(self.memory_path, latest.read_text(encoding="utf-8"))
        latest.unlink()
        entry = {"at": _now(), "source": "undo", "input": "", "changes": ["Undid the previous change"]}
        with self.history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True

    # ---- settings -----------------------------------------------------

    def load_settings(self) -> dict:
        defaults = {"auto_rebuild": True, "target": "", "page_size": "A4", "ai_backend": "", "ai_model": "",
                    "section_order": [], "hidden_sections": [],
                    "template": "classic", "accent": "#1f4e79", "fit_one_page": False}
        if self.settings_path.exists():
            defaults.update(json.loads(self.settings_path.read_text(encoding="utf-8")))
        return defaults

    def save_settings(self, settings: dict) -> dict:
        merged = self.load_settings()
        merged.update({k: v for k, v in settings.items() if k in merged})
        _write_atomic(self.settings_path, json.dumps(merged, indent=2))
        return merged

    # ---- CV -----------------------------------------------------------

    def save_cv(self, cv: CVDocument, html: str, target: str) -> None:
        _write_atomic(self.cv_json_path, cv.model_dump_json(indent=2))
        _write_atomic(self.cv_html_path, html)
        meta = {"generated_at": _now(), "target": target, "edited": False}
        _write_atomic(self.cv_meta_path, json.dumps(meta, indent=2))

    def save_cv_html(self, html: str) -> None:
        """Replace the CV page (e.g. after re-arranging sections) without marking it as hand-edited."""
        _write_atomic(self.cv_html_path, html)

    def save_cv_edits(self, html: str) -> None:
        _write_atomic(self.cv_html_path, html)
        meta = self.cv_meta()
        meta.update({"edited": True, "edited_at": _now()})
        _write_atomic(self.cv_meta_path, json.dumps(meta, indent=2))

    def mark_cv_edits_learned(self) -> None:
        meta = self.cv_meta()
        meta["edited"] = False
        _write_atomic(self.cv_meta_path, json.dumps(meta, indent=2))

    def load_cv(self) -> CVDocument | None:
        if not self.cv_json_path.exists():
            return None
        return CVDocument.model_validate_json(self.cv_json_path.read_text(encoding="utf-8"))

    def cv_html(self) -> str:
        return self.cv_html_path.read_text(encoding="utf-8") if self.cv_html_path.exists() else ""

    def cv_meta(self) -> dict:
        if not self.cv_meta_path.exists():
            return {}
        return json.loads(self.cv_meta_path.read_text(encoding="utf-8"))
