from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .evidence_artifacts import compile_staged_ledgers
from .evidence_contract import EvidenceClaim, EvidenceLedger
from .evidence_scheduler import next_generated_action
from .experiment_identity import build_experiment_identity
from .promotion_policy import GENERATED_CRITIC_ELIGIBLE, evaluate_promotion
from .provider_performance import compile_provider_performance


@dataclass(frozen=True, slots=True)
class ShadowEvidenceObservation:
    event_key: str
    event_id: str
    experiment_fingerprint: str
    stage: str
    race: str
    lineage: str
    build_id: str
    promotion: dict
    scheduler: dict
    scope_states: dict[str, str]


def _ledger_from_payload(payload: dict) -> EvidenceLedger:
    return EvidenceLedger(
        subject_id=str(payload["subject_id"]),
        lineage=str(payload["lineage"]),
        claims=[EvidenceClaim(**row) for row in payload.get("claims", [])],
    )


def _jsonable(value):
    """Canonicalize Python containers to the representation that JSON persists."""
    return json.loads(json.dumps(value, sort_keys=True))


def _canonical_digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _safe_component(value: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value))
    normalized = normalized.strip("-")
    if not normalized:
        raise ValueError("evidence path component cannot be empty")
    return normalized


class EvidenceDirectedDirector:
    """Observe a tournament with immutable evidence while leaving routing unchanged.

    v0.11 is intentionally shadow-only. This class is allowed to fingerprint the
    experiment, materialize evidence ledgers, evaluate promotion policy, and record
    what the evidence scheduler *would* do next. It is not allowed to execute that
    recommendation or alter provider selection.
    """

    def __init__(self, root: Path, identity: dict):
        self.root = root
        self.identity = identity
        self.events_path = root / "shadow-events.jsonl"

    @classmethod
    def initialize(
        cls,
        root: Path,
        *,
        brief_path: Path,
        provider_configs: Mapping[str, Path],
        seed: int,
        browsers: Iterable[str],
        git_sha: str | None = None,
    ) -> "EvidenceDirectedDirector":
        identity = build_experiment_identity(
            brief_path=brief_path,
            provider_configs=provider_configs,
            seed=seed,
            browsers=browsers,
            git_sha=git_sha,
        )
        root.mkdir(parents=True, exist_ok=True)
        identity_path = root / "experiment-identity.json"
        if identity_path.exists():
            existing = json.loads(identity_path.read_text())
            if existing.get("experiment_fingerprint") != identity.get("experiment_fingerprint"):
                raise ValueError(
                    "evidence-directed root already belongs to a different experiment: "
                    f"{existing.get('experiment_fingerprint')} != {identity.get('experiment_fingerprint')}"
                )
            if existing != identity:
                raise ValueError("experiment identity fingerprint matched but payload differed")
        else:
            identity_path.write_text(json.dumps(identity, indent=2) + "\n")
        return cls(root, identity)

    def observe_staged_evidence(
        self,
        *,
        race: str,
        staged_evidence_path: Path,
        lineage: str = "generated-web",
    ) -> dict:
        """Compile immutable per-build ledgers and shadow decisions for one race."""
        race_key = _safe_component(race)
        lineage_key = _safe_component(lineage)
        ledger_root = self.root / "ledgers" / lineage_key / race_key
        rows = compile_staged_ledgers(
            staged_evidence_path,
            ledger_root,
            lineage=lineage,
        )

        observations: dict[str, dict] = {}
        for build_id, payload in sorted(rows.items()):
            ledger = _ledger_from_payload(payload)
            # Canonicalize before hashing or equality checks. Dataclass tuples become
            # JSON arrays on disk; comparing the pre-serialization object to a reread
            # JSON row would otherwise create a false immutable-event conflict.
            promotion = _jsonable(asdict(evaluate_promotion(ledger, GENERATED_CRITIC_ELIGIBLE)))
            scheduler = _jsonable(asdict(next_generated_action(ledger)))
            base = {
                "experiment_fingerprint": self.identity["experiment_fingerprint"],
                "stage": "staged_evidence",
                "race": race_key,
                "lineage": lineage,
                "build_id": str(build_id),
                "promotion": promotion,
                "scheduler": scheduler,
                "scope_states": dict(payload.get("scope_states", {})),
            }
            event_key = f"staged_evidence:{lineage}:{race_key}:{build_id}"
            event_id = _canonical_digest({"event_key": event_key, **base})
            event = _jsonable(asdict(ShadowEvidenceObservation(
                event_key=event_key,
                event_id=event_id,
                experiment_fingerprint=base["experiment_fingerprint"],
                stage=base["stage"],
                race=base["race"],
                lineage=base["lineage"],
                build_id=base["build_id"],
                promotion=promotion,
                scheduler=scheduler,
                scope_states=base["scope_states"],
            )))
            self._append_event(event)
            observations[str(build_id)] = event

        summary = {
            "schema_version": "0.1",
            "mode": "shadow",
            "routing_authority": False,
            "experiment_fingerprint": self.identity["experiment_fingerprint"],
            "stage": "staged_evidence",
            "race": race_key,
            "lineage": lineage,
            "source_artifact": str(staged_evidence_path),
            "observations": observations,
        }
        summary_path = self.root / "observations" / lineage_key / f"{race_key}.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        if summary_path.exists():
            existing = json.loads(summary_path.read_text())
            if existing != summary:
                raise ValueError(f"conflicting shadow observation already exists: {summary_path}")
        else:
            summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        return summary

    def compile_provider_shadow(self, run_root: Path) -> dict:
        """Materialize provider outcomes for inspection without changing routing."""
        path = self.root / "provider-performance.json"
        payload = compile_provider_performance(run_root, path)
        if payload.get("routing_authority") is not False:
            raise ValueError("provider performance unexpectedly acquired routing authority")
        return payload

    def _append_event(self, event: dict) -> None:
        existing_by_key: dict[str, dict] = {}
        if self.events_path.exists():
            for line in self.events_path.read_text().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                existing_by_key[str(row["event_key"])] = row

        key = str(event["event_key"])
        existing = existing_by_key.get(key)
        if existing is not None:
            if existing != event:
                raise ValueError(f"conflicting immutable evidence event for {key}")
            return

        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
