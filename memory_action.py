"""Phase 3B-R minimal tool-action layer with proposal-only memory changes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from memory_proposal import SemanticProposalService


@dataclass(frozen=True, slots=True)
class ToolResult:
    success: bool
    value: Any = None
    candidate_change: Mapping[str, Any] | None = None
    error: str | None = None


def recommend_drink(memory_context: Mapping[str, Any]) -> ToolResult:
    preference = memory_context.get("favorite_drink")
    return ToolResult(True, preference or "一般飲料建議")


def query_user_city(memory_context: Mapping[str, Any]) -> ToolResult:
    return ToolResult(True, memory_context.get("city"))


def save_user_preference(candidate: Mapping[str, Any], *, fail: bool = False) -> ToolResult:
    """Return a candidate only. This tool never writes Memory Core."""
    if fail:
        return ToolResult(False, error="tool_execution_failed")
    return ToolResult(True, value="candidate_created", candidate_change=dict(candidate))


class ActionService:
    def __init__(self, *, proposals: SemanticProposalService):
        self.proposals = proposals

    def execute_task(
        self,
        *,
        user_id: str,
        session_id: str,
        task: str,
        selected_tool: str,
        candidate_change: Mapping[str, Any] | None = None,
        fail_tool: bool = False,
    ) -> dict[str, Any]:
        snapshot = self.proposals.store.get_typed_protocol_snapshot(user_id, session_id)
        context = _context_from_snapshot(snapshot)
        if selected_tool == "recommend_drink":
            tool_result = recommend_drink(context)
            proposal = None
        elif selected_tool == "query_user_city":
            tool_result = query_user_city(context)
            proposal = None
        elif selected_tool == "save_user_preference":
            if candidate_change is None:
                raise ValueError("save_user_preference requires a candidate")
            tool_result = save_user_preference(candidate_change, fail=fail_tool)
            proposal = None
            if tool_result.success and tool_result.candidate_change is not None:
                proposal = self.proposals.create_proposal(
                    user_id=user_id,
                    session_id=session_id,
                    source="tool_action",
                    source_text=task,
                    candidate_operation=tool_result.candidate_change,
                )
        else:
            raise ValueError("unsupported tool")
        return {
            "selected_tool": selected_tool,
            "tool_result": asdict(tool_result),
            "memory_context": context,
            "proposal": None if proposal is None else asdict(proposal),
            "memory_updated": False,
            "review_status": None if proposal is None else "HUMAN_REVIEW_REQUIRED",
        }


def _context_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    names = {
        "user.favorite_drink": "favorite_drink",
        "person.residence.location": "city",
    }
    for item in snapshot["current"]:
        key = names.get(item.get("semantic_key"))
        state = item.get("state")
        if key is not None and isinstance(state, Mapping):
            result[key] = state.get("value")
    return result
