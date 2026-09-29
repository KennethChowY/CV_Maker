"""What the AI has been used for, and roughly what it cost, so an API key never surprises you.

Each request's token counts go into data/usage.jsonl. Costs are estimates from the price list
below; the AI service's own billing page is the final word.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

# US dollars per million tokens (input, output). Matched by model-name prefix.
PRICES = {
    "claude-opus-5": (4.0, 20.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4": (1.0, 5.0),
}

PURPOSES = {
    "MemoryUpdate": "Adding to memory",
    "CVWording": "Writing the CV",
    "BulletSuggestions": "Improving bullets",
    "CoverLetter": "Cover letters and statements",
    "TruthReport": "Truth checks",
    "StrengthenQuestions": "Strengthening questions",
    "InterviewPrep": "Interview prep",
    "Email": "Emails",
    "SupervisorEmail": "Emails to professors",
    "PaperMatch": "Emails to professors",
    "EmailPieces": "Emails to professors",
    "MemoryReview": "Reviewing memory",
    "LinkedInProfile": "LinkedIn text",
    "CVDocument": "Translation",
}


def price(provider: str, model: str) -> tuple[float, float] | None:
    if provider == "ollama":
        return (0.0, 0.0)
    for prefix, p in PRICES.items():
        if model.startswith(prefix):
            return p
    return None


class UsageLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, provider: str, model: str, purpose: str, input_tokens: int, output_tokens: int) -> None:
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "provider": provider,
                 "model": model, "purpose": purpose, "in": int(input_tokens or 0), "out": int(output_tokens or 0)}
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def summary(self) -> dict:
        """Totals for this month and for all time, with a cost estimate where prices are known."""
        month = datetime.now(timezone.utc).strftime("%Y-%m")

        def total(rows: list[dict]) -> dict:
            cost, unpriced = 0.0, 0
            by_purpose: dict[str, dict] = {}
            for r in rows:
                p = price(r.get("provider", ""), r.get("model", ""))
                c = (r["in"] * p[0] + r["out"] * p[1]) / 1e6 if p else 0.0
                unpriced += p is None
                cost += c
                label = PURPOSES.get(r.get("purpose", ""), r.get("purpose", "") or "Other")
                slot = by_purpose.setdefault(label, {"purpose": label, "requests": 0, "tokens": 0, "cost": 0.0})
                slot["requests"] += 1
                slot["tokens"] += r["in"] + r["out"]
                slot["cost"] = round(slot["cost"] + c, 4)
            return {"requests": len(rows), "input_tokens": sum(r["in"] for r in rows),
                    "output_tokens": sum(r["out"] for r in rows), "cost": round(cost, 4),
                    "unpriced": unpriced, "local": sum(r.get("provider") == "ollama" for r in rows),
                    "by_purpose": sorted(by_purpose.values(), key=lambda x: -x["tokens"])}

        rows = self.entries()
        return {"month": total([r for r in rows if r.get("at", "").startswith(month)]), "all": total(rows)}
