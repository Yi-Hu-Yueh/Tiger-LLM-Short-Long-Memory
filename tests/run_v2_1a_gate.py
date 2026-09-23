"""One-pass real-provider gate. Emits metrics only, never raw model data."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from memory_v2_semantic.semantic_adapter import DeepSeekPlanProvider, ScalarSemanticAdapter  # noqa: E402
from memory_v2_semantic.semantic_validator import PlanValidationError  # noqa: E402
from v2_1a_cases import Case, development_cases, holdout_cases  # noqa: E402


class CountingProvider:
    def __init__(self):
        self.provider = DeepSeekPlanProvider()
        self.lock = Lock()
        self.attempts = 0
        self.responses = 0

    def complete(self, messages: list[dict[str, str]]) -> str:
        with self.lock:
            self.attempts += 1
        result = self.provider.complete(messages)
        with self.lock:
            self.responses += 1
        return result


def _run_one(case: Case, provider: CountingProvider) -> tuple[bool, bool, str]:
    try:
        plan = ScalarSemanticAdapter(provider).propose(case.message, case.candidates)
    except PlanValidationError as exc:
        return False, False, "STRUCTURE:" + exc.code
    except Exception as exc:
        # Do not expose raw provider response or request headers.
        return False, False, "PROVIDER:" + type(exc).__name__
    structural = plan.mutation_count == 0
    semantic = (
        plan.intent == case.intent and
        plan.target_memory_id == case.target_id and
        plan.value_candidate == case.literal and
        plan.temporal_relation == case.temporal and
        plan.reason_code == case.reason
    )
    return structural, semantic, "OK" if semantic else "SEMANTIC_MISMATCH"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("development", "holdout"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    cases = development_cases() if args.phase == "development" else holdout_cases()
    provider = CountingProvider()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda case: _run_one(case, provider), cases))
    total = len(cases)
    structural_count = sum(row[0] for row in results)
    semantic_count = sum(row[1] for row in results)
    critical = [(case, result) for case, result in zip(cases, results) if case.critical]
    critical_pass = sum(result[1] for _, result in critical)
    failure_categories = Counter(case.category for case, result in zip(cases, results)
                                 if not result[1])
    failures = [
        {"case_id": case.case_id, "category": case.category, "code": result[2]}
        for case, result in zip(cases, results) if not result[1]
    ]
    print(json.dumps({
        "phase": args.phase,
        "total": total,
        "structural_pass": structural_count,
        "structural_rate": round(structural_count / total, 4),
        "semantic_pass": semantic_count,
        "semantic_rate": round(semantic_count / total, 4),
        "critical_total": len(critical),
        "critical_pass": critical_pass,
        "critical_rate": round(critical_pass / len(critical), 4),
        "provider_attempts": provider.attempts,
        "provider_responses": provider.responses,
        "failure_categories": dict(sorted(failure_categories.items())),
        "failures": failures,
        "canonical_mutations": 0,
    }, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
