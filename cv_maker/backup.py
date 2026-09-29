"""Backups: a zip of the data folder (never the API key), on demand or automatically,
at most once an hour, to a folder of your choice such as iCloud Drive."""

from __future__ import annotations

import io
import time
import zipfile
from datetime import datetime
from pathlib import Path

EXCLUDE = {"secrets.json"}
PREFIX = "CV Maker backup "
KEEP = 30
EVERY_SECONDS = 3600


def backup_zip(data_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(data_dir.rglob("*")):
            if path.is_file() and path.name not in EXCLUDE and not path.name.endswith(".tmp"):
                z.write(path, f"data/{path.relative_to(data_dir).as_posix()}")
    return buffer.getvalue()


def suggested_folder() -> str:
    """iCloud Drive on a Mac, so backups reach your other devices; otherwise Documents."""
    icloud = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    base = icloud if icloud.is_dir() else Path.home() / "Documents"
    return str(base / "CV Maker Backups")


def check_folder(folder: str) -> Path:
    """The folder as an absolute path, created if needed. Raises ValueError if it can't be used."""
    path = Path(folder).expanduser()
    if not path.is_absolute():
        raise ValueError("Use a full folder path, like ~/Documents/CV Maker Backups.")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".cv-maker-write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as e:
        raise ValueError(f"Can't save backups in that folder: {e.strerror or e}.") from e
    return path


def _existing(folder: Path) -> list[Path]:
    return sorted(folder.glob(f"{PREFIX}*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)


def auto_backup(data_dir: Path, folder: str, *, force: bool = False) -> Path | None:
    """Write a backup if one is due (or `force`), keeping the newest KEEP. Returns the new file."""
    if not folder:
        return None
    target = check_folder(folder)
    existing = _existing(target)
    if existing and not force and time.time() - existing[0].stat().st_mtime < EVERY_SECONDS:
        return None
    stamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    path, n = target / f"{PREFIX}{stamp}.zip", 1
    while path.exists():
        n += 1
        path = target / f"{PREFIX}{stamp} ({n}).zip"
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(backup_zip(data_dir))
    tmp.replace(path)
    for old in _existing(target)[KEEP:]:
        old.unlink(missing_ok=True)
    return path


def status(folder: str) -> dict:
    info = {"folder": folder, "suggested": suggested_folder(), "last": "", "count": 0}
    if folder:
        path = Path(folder).expanduser()
        existing = _existing(path) if path.is_dir() else []
        if existing:
            info["last"] = datetime.fromtimestamp(existing[0].stat().st_mtime).isoformat(timespec="seconds")
            info["count"] = len(existing)
    return info
