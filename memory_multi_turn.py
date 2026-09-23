"""Phase 2B minimal multi-turn memory behavior gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_answer import DeepSeekAnswerGenerator
from memory_core import SQLiteMemoryCore
from memory_extractor import MemoryExtractor, create_memory_extractor_from_env
from memory_runtime import CORE_SUBJECT, MemoryRuntimeService


@dataclass(frozen=True, slots=True)
class TurnResult:
    user_id: str
    session_id: str
    message: str
    extraction_result: dict[str, Any]
    memory_context: dict[str, Any]
    assistant_response: str
    answer_latency_seconds: float
    answer_api_calls: int
    answer_token_usage: dict[str, int]


class MultiTurnMemoryService:
    """Small orchestration layer for validation, not a full agent."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        extractor: MemoryExtractor | None = None,
        answer_generator: DeepSeekAnswerGenerator | None = None,
    ):
        self.runtime = MemoryRuntimeService(
            core=SQLiteMemoryCore(db_path),
            extractor=extractor or create_memory_extractor_from_env(),
        )
        self.answer_generator = answer_generator or DeepSeekAnswerGenerator()

    def run_turn(self, *, user_id: str, session_id: str, message: str) -> TurnResult:
        extraction_result = self.runtime.process_user_message(user_id, session_id, message)
        context = self.runtime.get_memory_context(user_id)
        answer = self.answer_generator.answer(message, context)
        return TurnResult(
            user_id=user_id,
            session_id=session_id,
            message=message,
            extraction_result=extraction_result,
            memory_context=context,
            assistant_response=answer.response,
            answer_latency_seconds=answer.latency_seconds,
            answer_api_calls=answer.api_calls,
            answer_token_usage=answer.token_usage,
        )

    def get_history_values(self, user_id: str, attribute: str) -> list[Any]:
        return [
            fact.value
            for fact in self.runtime.core.get_fact_history(user_id, CORE_SUBJECT, attribute)
        ]
