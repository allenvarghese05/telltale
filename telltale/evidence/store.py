"""Immutable, SHA-256-hashed evidence store shared by the agent, the checker and the UI."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from telltale.core.schema import HIDDEN_FROM_AGENT, Fact

TOOL_PREFIXES = ("WIT2:", "CF:")


class EvidenceStore:
    """Facts plus time series. Never mutated: `extended` returns a new store with a new digest."""

    def __init__(self, facts: list[Fact], series: dict | None = None) -> None:
        self._facts: dict[str, Fact] = {}
        for fact in facts:
            if fact.id in self._facts:
                raise ValueError(f"duplicate fact id {fact.id}")
            self._facts[fact.id] = fact
        self._series = {
            name: {
                "t": [float(x) for x in s["t"]],
                "v": [float(x) for x in s["v"]],
                "unit": s.get("unit", ""),
                "source": s.get("source", ""),
            }
            for name, s in (series or {}).items()
        }
        self.parent_digest: str | None = None
        self.digest = self._compute_digest()

    def _compute_digest(self) -> str:
        payload = {
            "facts": [asdict(self._facts[k]) for k in sorted(self._facts)],
            "series": {k: self._series[k] for k in sorted(self._series)},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def has(self, fact_id: str) -> bool:
        return fact_id in self._facts

    def get(self, fact_id: str) -> Fact:
        return self._facts[fact_id]

    def facts(self) -> list[Fact]:
        return [self._facts[k] for k in sorted(self._facts)]

    def agent_facts(self) -> list[Fact]:
        """Facts the investigator may see: the checker's own derivations are hidden."""
        return [f for f in self.facts() if not f.id.startswith(HIDDEN_FROM_AGENT)]

    def series_names(self) -> list[str]:
        return sorted(self._series)

    def series(self, name: str, t0: float | None = None, t1: float | None = None) -> dict:
        s = self._series[name]
        keep = [i for i, t in enumerate(s["t"]) if (t0 is None or t >= t0) and (t1 is None or t <= t1)]
        return {
            "t": [s["t"][i] for i in keep],
            "v": [s["v"][i] for i in keep],
            "unit": s["unit"],
            "source": s["source"],
        }

    def extended(self, new_facts: list[Fact]) -> EvidenceStore:
        """Append facts produced by agent tool code (witness rechecks, counterfactual runs) and nothing else."""
        for fact in new_facts:
            if not fact.id.startswith(TOOL_PREFIXES):
                raise PermissionError(f"only tool-generated {TOOL_PREFIXES} facts may be appended, got {fact.id}")
        child = EvidenceStore(self.facts() + list(new_facts), self._series)
        child.parent_digest = self.digest
        return child

    def verify_integrity(self) -> bool:
        return self._compute_digest() == self.digest

    def to_json(self) -> dict:
        return {
            "digest": self.digest,
            "parent_digest": self.parent_digest,
            "facts": [asdict(f) for f in self.facts()],
            "series": self._series,
        }

    @classmethod
    def from_json(cls, data: dict) -> EvidenceStore:
        store = cls([Fact(**f) for f in data["facts"]], data["series"])
        if store.digest != data["digest"]:
            raise ValueError("evidence digest mismatch: store was modified")
        store.parent_digest = data.get("parent_digest")
        return store
