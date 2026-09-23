"""Staged append-only runner for the frozen ontology/risk held-out benchmark.

This module orchestrates the already-frozen evaluator.  It never writes memory,
History, revisions, or proposals.  Results are append-only JSONL evidence in a
dedicated benchmark-results directory.  The runner verifies freeze integrity
before every stage and stops immediately on unsafe or forbidden-risk auto
simulation evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import fields
from pathlib import Path
from typing import Mapping

import ontology_benchmark
import ontology_diagnostic


PRODUCTION_ACTIVE = False
HELDOUT_STATUS_ENDPOINT = "/api/ontology-benchmark/heldout-status"
HELDOUT_NEXT_ENDPOINT = "/api/ontology-benchmark/heldout-next"
STAGE_TARGETS = (10, 50, 100, 200, 300, 400, 500, 600, 660)
RESULT_ROOT = Path(__file__).resolve().parent / "data" / "ontology_benchmark_runs"
RESULT_SCHEMA_VERSION = 1


class HeldoutRunnerError(ValueError):
    """Fail-closed held-out runner error."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_freeze_token(freeze_id: str) -> str:
    token = "".join(ch for ch in freeze_id if ch.isalnum() or ch in ("-", "_", "."))
    if not token or token != freeze_id:
        raise HeldoutRunnerError("Invalid freeze_id for benchmark result storage")
    return token


def _evaluation_from_dict(value: Mapping[str, object]) -> ontology_benchmark.BenchmarkEvaluation:
    names = {field.name for field in fields(ontology_benchmark.BenchmarkEvaluation)}
    if set(value) != names:
        raise HeldoutRunnerError("Stored benchmark evaluation schema mismatch")
    return ontology_benchmark.BenchmarkEvaluation(**{name: value[name] for name in names})


class HeldoutBenchmarkRunner:
    """Runs one preregistered held-out stage per explicit user action."""

    def __init__(self, provider, result_root: Path | None = None):
        self._provider = provider
        self._result_root = Path(result_root) if result_root is not None else RESULT_ROOT
        self._lock = threading.Lock()

    def _result_path(self, freeze_id: str) -> Path:
        return self._result_root / f"heldout_{_safe_freeze_token(freeze_id)}.jsonl"

    def _read_records(self, freeze_id: str) -> list[dict[str, object]]:
        path = self._result_path(freeze_id)
        if not path.exists():
            return []
        records: list[dict[str, object]] = []
        previous_hash = "GENESIS"
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    raise HeldoutRunnerError(f"Blank held-out result line {line_number}")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    raise HeldoutRunnerError(f"Invalid held-out result line {line_number}") from None
                if not isinstance(record, dict):
                    raise HeldoutRunnerError("Held-out result record must be an object")
                expected_keys = {
                    "schema_version", "freeze_id", "ordinal", "case_id", "evaluation",
                    "previous_record_sha256", "record_sha256",
                }
                if set(record) != expected_keys:
                    raise HeldoutRunnerError("Held-out result record schema mismatch")
                if record["schema_version"] != RESULT_SCHEMA_VERSION or record["freeze_id"] != freeze_id:
                    raise HeldoutRunnerError("Held-out result identity mismatch")
                if record["previous_record_sha256"] != previous_hash:
                    raise HeldoutRunnerError("Held-out result hash chain mismatch")
                content = {key: record[key] for key in record if key != "record_sha256"}
                actual_hash = hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()
                if actual_hash != record["record_sha256"]:
                    raise HeldoutRunnerError("Held-out result record hash mismatch")
                ordinal = int(record["ordinal"])
                expected_ordinal = len(records) + 1
                if ordinal != expected_ordinal:
                    raise HeldoutRunnerError("Held-out result ordinal sequence mismatch")
                expected_case = ontology_benchmark.DATASET[ordinal - 1]
                if record["case_id"] != expected_case.case_id:
                    raise HeldoutRunnerError("Held-out result case order mismatch")
                if not isinstance(record["evaluation"], dict):
                    raise HeldoutRunnerError("Held-out evaluation payload is invalid")
                _evaluation_from_dict(record["evaluation"])
                previous_hash = str(record["record_sha256"])
                records.append(record)
        if len(records) > len(ontology_benchmark.DATASET):
            raise HeldoutRunnerError("Held-out result count exceeds frozen dataset")
        return records

    def _append_record(
        self,
        freeze_id: str,
        ordinal: int,
        evaluation: ontology_benchmark.BenchmarkEvaluation,
        previous_hash: str,
    ) -> dict[str, object]:
        path = self._result_path(freeze_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        content: dict[str, object] = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "freeze_id": freeze_id,
            "ordinal": ordinal,
            "case_id": evaluation.case_id,
            "evaluation": ontology_benchmark.evaluation_dict(evaluation),
            "previous_record_sha256": previous_hash,
        }
        record_hash = hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()
        record = {**content, "record_sha256": record_hash}
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    @staticmethod
    def _partial_summary(records: list[dict[str, object]]) -> dict[str, object]:
        evaluations = [_evaluation_from_dict(record["evaluation"]) for record in records]  # type: ignore[arg-type]
        total = len(evaluations)
        auto_turns = sum(row.category == "AUTO_ELIGIBLE" for row in evaluations)
        guardrails = total - auto_turns
        operand_den = sum(
            bool(ontology_benchmark.DATASET_BY_ID[row.case_id].acceptable_literals)
            for row in evaluations
        )
        unsafe = sum(row.unsafe_auto_commit for row in evaluations)
        forbidden = sum(row.forbidden_risk_auto_commit for row in evaluations)
        slot_errors = sum(row.slot_error for row in evaluations)
        operand_errors = sum(row.operand_value_error for row in evaluations)
        protocol_failures = sum(row.protocol_failure for row in evaluations)
        human_reviews = sum(row.human_review for row in evaluations)
        safe_auto = sum(row.safe_automatic_completion for row in evaluations)
        non_writes = sum(row.non_write for row in evaluations)
        return {
            "completed_turns": total,
            "remaining_turns": len(ontology_benchmark.DATASET) - total,
            "auto_eligible_turns_completed": auto_turns,
            "guardrail_turns_completed": guardrails,
            "provider_calls": sum(row.provider_calls for row in evaluations),
            "unsafe_auto_commits": unsafe,
            "forbidden_risk_auto_commits": forbidden,
            "slot_errors": slot_errors,
            "operand_value_errors": operand_errors,
            "protocol_failures": protocol_failures,
            "human_reviews": human_reviews,
            "safe_automatic_completions": safe_auto,
            "non_writes": non_writes,
            "slot_error_rate_so_far": (slot_errors / total) if total else 0.0,
            "operand_value_error_rate_so_far": (operand_errors / operand_den) if operand_den else 0.0,
            "protocol_failure_rate_so_far": (protocol_failures / total) if total else 0.0,
            "human_review_rate_so_far": (human_reviews / total) if total else 0.0,
            "safe_automatic_completion_rate_so_far": (safe_auto / total) if total else 0.0,
            "mandatory_safety_stop": bool(unsafe or forbidden),
        }

    @staticmethod
    def _failure_evidence(records: list[dict[str, object]], limit: int = 10) -> list[dict[str, object]]:
        evidence: list[dict[str, object]] = []
        for record in records:
            row = _evaluation_from_dict(record["evaluation"])  # type: ignore[arg-type]
            if (
                row.protocol_failure
                or row.slot_error
                or row.claim_shape_error
                or row.entity_target_error
                or row.operand_value_error
                or row.operation_error
                or row.resulting_state_error
                or row.unsafe_auto_commit
                or row.forbidden_risk_auto_commit
            ):
                evidence.append({
                    "ordinal": record["ordinal"],
                    "case_id": row.case_id,
                    "state": row.state,
                    "diagnostic": row.diagnostic,
                    "protocol_failure": row.protocol_failure,
                    "slot_error": row.slot_error,
                    "claim_shape_error": row.claim_shape_error,
                    "entity_target_error": row.entity_target_error,
                    "operand_value_error": row.operand_value_error,
                    "operation_error": row.operation_error,
                    "resulting_state_error": row.resulting_state_error,
                    "unsafe_auto_commit": row.unsafe_auto_commit,
                    "forbidden_risk_auto_commit": row.forbidden_risk_auto_commit,
                    "semantic_oracle_match": row.semantic_oracle_match,
                    "benchmark_route": row.benchmark_route,
                })
                if len(evidence) >= limit:
                    break
        return evidence

    def status(self) -> dict[str, object]:
        freeze = ontology_benchmark.verify_freeze()
        freeze_id = str(freeze.get("freeze_id") or "")
        records = self._read_records(freeze_id) if freeze_id else []
        completed = len(records)
        locked = bool(records and self._partial_summary(records)["mandatory_safety_stop"])
        next_target = next((target for target in STAGE_TARGETS if target > completed), None)
        final_summary = None
        if completed == len(ontology_benchmark.DATASET):
            final_summary = ontology_benchmark.summary_dict(
                ontology_benchmark.summarize(
                    [_evaluation_from_dict(record["evaluation"]) for record in records]  # type: ignore[arg-type]
                )
            )
            locked = True
        return {
            "official_heldout": True,
            "status": freeze["status"],
            "freeze_id": freeze_id,
            "procedure_version": freeze["procedure_version"],
            "dataset_turns": len(ontology_benchmark.DATASET),
            "stage_targets": list(STAGE_TARGETS),
            "completed_turns": completed,
            "next_stage_target": next_target,
            "next_stage_calls": (next_target - completed) if next_target is not None else 0,
            "run_started": bool(records),
            "run_complete": completed == len(ontology_benchmark.DATASET),
            "run_locked": locked,
            "partial_summary": self._partial_summary(records) if records else None,
            "failure_evidence": self._failure_evidence(records),
            "final_summary": final_summary,
            "result_file": self._result_path(freeze_id).name if freeze_id else None,
            "zero_memory_persistence": True,
        }

    def run_next_stage(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict) or not set(request).issubset({"confirmed", "api_key"}):
            raise HeldoutRunnerError("Held-out stage request accepts only confirmed and api_key")
        if request.get("confirmed") is not True:
            raise HeldoutRunnerError("Explicit held-out stage confirmation is required")
        freeze = ontology_benchmark.verify_freeze()
        if freeze["status"] != "FROZEN":
            raise HeldoutRunnerError("Benchmark freeze drift detected; held-out run is blocked")
        if not ontology_benchmark.HELDOUT_BATCH_RUN_ENABLED:
            raise HeldoutRunnerError("Held-out staged run is disabled")
        api_key = request.get("api_key")
        if api_key is not None and not isinstance(api_key, str):
            raise HeldoutRunnerError("api_key must be text")
        key = os.environ.get("DEEPSEEK_API_KEY") or (api_key or "").strip()
        if not key:
            raise HeldoutRunnerError("Provide DEEPSEEK_API_KEY or API key fallback")
        freeze_id = str(freeze["freeze_id"])
        with self._lock:
            records = self._read_records(freeze_id)
            partial = self._partial_summary(records) if records else None
            if partial and partial["mandatory_safety_stop"]:
                raise HeldoutRunnerError("Held-out run is permanently stopped by safety evidence")
            if len(records) >= len(ontology_benchmark.DATASET):
                raise HeldoutRunnerError("Held-out benchmark is already complete")
            target = next((value for value in STAGE_TARGETS if value > len(records)), None)
            if target is None:
                raise HeldoutRunnerError("No held-out stage remains")
            stage_start = len(records) + 1
            previous_hash = str(records[-1]["record_sha256"]) if records else "GENESIS"
            stage_records: list[dict[str, object]] = []
            safety_stop = False
            for ordinal in range(stage_start, target + 1):
                case = ontology_benchmark.DATASET[ordinal - 1]
                try:
                    raw = self._provider.complete(
                        ontology_diagnostic._prompt(ontology_benchmark._diagnostic_case(case)),
                        key,
                    )
                    evaluation = ontology_benchmark.evaluate_raw_response(case, raw)
                except Exception as exc:
                    evaluation = ontology_benchmark.provider_error_evaluation(
                        case, f"Provider call failed ({type(exc).__name__})"
                    )
                record = self._append_record(freeze_id, ordinal, evaluation, previous_hash)
                previous_hash = str(record["record_sha256"])
                records.append(record)
                stage_records.append(record)
                if evaluation.unsafe_auto_commit or evaluation.forbidden_risk_auto_commit:
                    safety_stop = True
                    break
            status = self.status()
            return {
                "official_heldout": True,
                "counted_in_heldout_metrics": True,
                "freeze_id": freeze_id,
                "stage_start_ordinal": stage_start,
                "stage_requested_target": target,
                "stage_completed_turns": len(stage_records),
                "stage_end_ordinal": len(records),
                "provider_calls_this_stage": len(stage_records),
                "safety_stop_triggered": safety_stop,
                "partial_summary": status["partial_summary"],
                "failure_evidence": status["failure_evidence"],
                "run_complete": status["run_complete"],
                "run_locked": status["run_locked"],
                "final_summary": status["final_summary"],
                "next_stage_target": status["next_stage_target"],
                "zero_memory_persistence": True,
            }
