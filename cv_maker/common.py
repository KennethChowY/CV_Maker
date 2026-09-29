"""Small shared types used by every AI backend."""

from __future__ import annotations

from dataclasses import dataclass


class AIError(RuntimeError):
    """A problem worth showing to the person, in plain words."""


@dataclass
class Attachment:
    filename: str
    media_type: str
    data: bytes
