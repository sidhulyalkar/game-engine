from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .evidence_artifacts import (
    compile_staged_ledgers,
    enrich_generated_ledger_with_critic_audit,
)
from .evidence_contract import EvidenceClaim, EvidenceLedger
from .evidence_scheduler import next_generated_action
from .experiment_identity import build_experiment_identity
from .promotion_policy import (
    FINAL_PLAYER_PROMOTION,
    GENERATED_CRITIC_ELIGIBLE,
    evaluate_promotion,
)
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

    The director is shadow-only. It fingerprints experiments, materializes capability
    ledgers, evaluates promotion policy, and records what the scheduler *would* do.
    It never executes that recommendation or changes provider selection.
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

    def _observation(
        self,
        *,
        event_key: str,
        stage: str,
        race: str,
        lineage: str,
        build_id: str,
        ledger_payload: dict,
        required_promotion_scopes,
    ) -> dict:
        ledger = _ledger_from_payload(ledger_payload)
        promotion = _jsonable(asdict(evaluate_promotion(ledger, required_promotion_scopes)))
        scheduler = _jsonable(asdict(next_generated_action(ledger)))
        base = {
            "experiment_fingerprint": self.identity["experiment_fingerprint"],
            "stage": stage,
            "race": race,
            "lineage": lineage,
            "build_id": build_id,
            "promotion": promotion,
            "scheduler": scheduler,
            "scope_states": dict(ledger_payload.get("scope_states", {})),
        }
        event_id = _canonical_digest({"event_key": event_key, **base})
        event = _jsonable(asdict(ShadowEvidenceObservation(
            event_key=event_key,
            event_id=event_id,
            experiment_fingerprint=base["experiment_fingerprint"],
            stage=stage,
            race=race,
            lineage=lineage,
            build_id=build_id,
            promotion=promotion,
            scheduler=scheduler,
            scope_states=base["scope_states"],
        )))
        self._append_event(event)
        return event

    def observe_staged_evidence(
        self,
        *,
        race: str,
        staged_evidence_path: Path,
        lineage: str = "generated-web",
    ) -> dict:
        """Compile immutable objective per-build ledgers and shadow decisions."""
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
            event_key = f"staged_evidence:{lineage}:{race_key}:{build_id}"
            observations[str(build_id)] = self._observation(
                event_key=event_key,
                stage="staged_evidence",
                race=race_key,
                lineage=lineage,
                build_id=str(build_id),
                ledger_payload=payload,
                required_promotion_scopes=GENERATED_CRITIC_ELIGIBLE,
            )

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
        self._write_immutable_summary(
            self.root / "observations" / lineage_key / f"{race_key}.json",
            summary,
        )
        return summary

    def observe_critic_audit(
        self,
        *,
        race: str,
        lineage: str,
        audit_summary_path: Path,
    ) -> dict:
        """Attach critic quorum + verdict to matching objective ledgers.

        Objective ledgers remain immutable in `ledgers/`. Derived critic-enriched
        ledgers are written separately under `critic-ledgers/` and get their own
        immutable event, preserving exactly what was known before critic spend.
        """
        race_key = _safe_component(race)
        lineage_key = _safe_component(lineage)
        audit = json.loads(audit_summary_path.read_text())
        ranking = [row for row in audit.get("ranking", []) if isinstance(row, dict)]
        if not ranking:
            raise ValueError(f"critic audit has no ranking rows: {audit_summary_path}")

        observations: dict[str, dict] = {}
        for row in ranking:
            build_id = str(row.get("build_id") or "")
            if not build_id:
                raise ValueError("critic audit ranking row is missing build_id")
            base_ledger = self.root / "ledgers" / lineage_key / race_key / f"{build_id}.json"
            if not base_ledger.exists():
                raise ValueError(
                    f"critic audit build {build_id} has no objective ledger for "
                    f"lineage={lineage} race={race_key}"
                )
            enriched_path = (
                self.root / "critic-ledgers" / lineage_key / race_key / f"{build_id}.json"
            )
            payload = enrich_generated_ledger_with_critic_audit(
                base_ledger,
                audit_summary_path,
                enriched_path,
            )
            event_key = f"critic_audit:{lineage}:{race_key}:{build_id}"
            observations[build_id] = self._observation(
                event_key=event_key,
                stage="critic_audit",
                race=race_key,
                lineage=lineage,
                build_id=build_id,
                ledger_payload=payload,
                required_promotion_scopes=FINAL_PLAYER_PROMOTION,
            )

        summary = {
            "schema_version": "0.1",
            "mode": "shadow",
            "routing_authority": False,
            "experiment_fingerprint": self.identity["experiment_fingerprint"],
            "stage": "critic_audit",
            "race": race_key,
            "lineage": lineage,
            "source_artifact": str(audit_summary_path),
            "observations": observations,
        }
        self._write_immutable_summary(
            self.root / "critic-observations" / lineage_key / f"{race_key}.json",
            summary,
        )
        return summary

    def compile_provider_shadow(self, run_root: Path) -> dict:
        """Materialize provider outcomes for inspection without changing routing."""
        path = self.root / "provider-performance.json"
        payload = compile_provider_performance(run_root, path)
        if payload.get("routing_authority") is not False:
            raise ValueError("provider performance unexpectedly acquired routing authority")
        return payload

    @staticmethod
    def _write_immutable_summary(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = json.loads(path.read_text())
            if existing != payload:
                raise ValueError(f"conflicting shadow observation already exists: {path}")
            return
        path.write_text(json.dumps(payload, indent=2) + "\n")

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
