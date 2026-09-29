"""File-backed memory store with history and undo.

Layout of the data directory:

    memory.json          current memory (source of truth)
    history.jsonl        one line per change: what you typed and what changed
    snapshots/*.json     memory as it was before each change (used for undo)
    cv.json              the general CV (structured), as last generated
    cv.html              the general CV page, including any manual edits
    cv_meta.json         when/for what it was generated, whether it was hand-edited
    letter.json          the general cover letter
    versions/<id>/       one folder per job application: info.json (company, role,
                         job ad, status…) plus its own cv.json, cv.html, cv_meta.json
                         and letter.json
    secrets.json         optional Claude API key, readable only by you
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .schema import CVDocument, Memory

_SECTIONS_WITH_IDS = ("experience", "education", "projects", "achievements")
GENERAL = "general"
STATUSES = ("Draft", "Applied", "Interview", "Offer", "Rejected", "Withdrawn")
_VERSION_FIELDS = ("company", "role", "name", "target", "link", "status", "applied", "notes")


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
        self.settings_path = self.dir / "settings.json"
        self.secrets_path = self.dir / "secrets.json"
        self.versions_dir = self.dir / "versions"

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
                    "active_version": GENERAL,
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

    # ---- API key ------------------------------------------------------

    def load_api_config(self) -> dict:
        """The saved API key and which service it's for: {"key", "provider", "base_url", "models"}."""
        if not self.secrets_path.exists():
            return {}
        data = json.loads(self.secrets_path.read_text(encoding="utf-8"))
        if "anthropic_api_key" in data and "key" not in data:  # saved by an earlier version of the app
            return {"key": data["anthropic_api_key"], "provider": "anthropic", "base_url": "", "models": []}
        return data

    def load_api_key(self) -> str:
        return self.load_api_config().get("key", "")

    def save_api_config(self, config: dict | None) -> None:
        if not config:
            self.secrets_path.unlink(missing_ok=True)
            return
        tmp = self.secrets_path.with_suffix(".tmp")
        # Create the file readable only by the current user before writing the key into it.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f)
        tmp.replace(self.secrets_path)

    # ---- versions (one per job application) ---------------------------

    def _slot(self, vid: str = GENERAL) -> Path:
        if vid == GENERAL:
            return self.dir
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,80}", vid or "") or not (self.versions_dir / vid).is_dir():
            raise KeyError(vid)
        return self.versions_dir / vid

    def has_version(self, vid: str) -> bool:
        try:
            self._slot(vid)
            return True
        except KeyError:
            return False

    def active_version(self) -> str:
        vid = self.load_settings()["active_version"]
        return vid if self.has_version(vid) else GENERAL

    def version_info(self, vid: str = GENERAL) -> dict:
        if vid == GENERAL:
            return {"id": GENERAL, "name": "General CV", "target": self.load_settings()["target"],
                    "company": "", "role": "", "status": "", "applied": "", "link": "", "notes": ""}
        return json.loads((self._slot(vid) / "info.json").read_text(encoding="utf-8"))

    def list_versions(self) -> list[dict]:
        if not self.versions_dir.exists():
            return []
        infos = [json.loads(p.read_text(encoding="utf-8")) for p in self.versions_dir.glob("*/info.json")]
        return sorted(infos, key=lambda i: i.get("created", ""), reverse=True)

    def create_version(self, *, company: str = "", role: str = "", target: str = "", link: str = "",
                       copy_from: str = GENERAL) -> dict:
        slug = re.sub(r"[^a-z0-9]+", "-", f"{company} {role}".lower()).strip("-")[:40] or "application"
        vid = f"{slug}-{secrets.token_hex(3)}"
        slot = self.versions_dir / vid
        slot.mkdir(parents=True)
        source = self._slot(copy_from)
        for name in ("cv.json", "cv.html", "cv_meta.json"):  # start from the current CV until rebuilt
            if (source / name).exists():
                shutil.copy(source / name, slot / name)
        info = {
            "id": vid, "company": company.strip(), "role": role.strip(),
            "name": " – ".join(x for x in (role.strip(), company.strip()) if x) or "Application",
            "target": target.strip(), "link": link.strip(), "status": "Draft", "applied": "", "notes": "",
            "created": _now(), "updated": _now(),
        }
        _write_atomic(slot / "info.json", json.dumps(info, indent=2))
        return info

    def update_version(self, vid: str, fields: dict) -> dict:
        if vid == GENERAL:
            if "target" in fields:
                self.save_settings({"target": str(fields["target"])})
            return self.version_info(GENERAL)
        info = self.version_info(vid)
        for key in _VERSION_FIELDS:
            if key in fields:
                info[key] = str(fields[key]).strip() if key != "target" else str(fields[key])
        if info["status"] not in STATUSES:
            info["status"] = "Draft"
        info["updated"] = _now()
        _write_atomic(self._slot(vid) / "info.json", json.dumps(info, indent=2))
        return info

    def delete_version(self, vid: str) -> None:
        if vid == GENERAL:
            raise KeyError(vid)
        shutil.rmtree(self._slot(vid))
        if self.load_settings()["active_version"] == vid:
            self.save_settings({"active_version": GENERAL})

    # ---- CV (of a version; the general CV by default) ---------------------

    def save_cv(self, cv: CVDocument, html: str, target: str, vid: str = GENERAL) -> None:
        slot = self._slot(vid)
        _write_atomic(slot / "cv.json", cv.model_dump_json(indent=2))
        _write_atomic(slot / "cv.html", html)
        meta = {"generated_at": _now(), "target": target, "edited": False}
        _write_atomic(slot / "cv_meta.json", json.dumps(meta, indent=2))

    def save_cv_html(self, html: str, vid: str = GENERAL) -> None:
        """Replace the CV page (e.g. after re-arranging sections) without marking it as hand-edited."""
        _write_atomic(self._slot(vid) / "cv.html", html)

    def save_cv_edits(self, html: str, vid: str = GENERAL) -> None:
        _write_atomic(self._slot(vid) / "cv.html", html)
        meta = self.cv_meta(vid)
        meta.update({"edited": True, "edited_at": _now()})
        _write_atomic(self._slot(vid) / "cv_meta.json", json.dumps(meta, indent=2))

    def mark_cv_edits_learned(self, vid: str = GENERAL) -> None:
        meta = self.cv_meta(vid)
        meta["edited"] = False
        _write_atomic(self._slot(vid) / "cv_meta.json", json.dumps(meta, indent=2))

    def load_cv(self, vid: str = GENERAL) -> CVDocument | None:
        path = self._slot(vid) / "cv.json"
        return CVDocument.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def cv_html(self, vid: str = GENERAL) -> str:
        path = self._slot(vid) / "cv.html"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def cv_meta(self, vid: str = GENERAL) -> dict:
        path = self._slot(vid) / "cv_meta.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    # ---- cover letter -------------------------------------------------

    def load_letter(self, vid: str = GENERAL) -> dict:
        path = self._slot(vid) / "letter.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def save_letter(self, letter: dict, vid: str = GENERAL) -> None:
        _write_atomic(self._slot(vid) / "letter.json", json.dumps(letter, indent=2))
