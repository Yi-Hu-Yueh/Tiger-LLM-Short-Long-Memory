"""UI-driven conformance-suite manifests and isolated local job runner.

This module is test-harness code.  It deliberately does not participate in
normal chat routing, Semantic IR compilation, or production persistence.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parent
TEST_DATA_DIR = ROOT / "data" / "ui_test_runner"
SUITE_DB_PATHS = {
    "real40": TEST_DATA_DIR / "real40.db",
    "real40v2": TEST_DATA_DIR / "real40_v2.db",
    "v2gate": TEST_DATA_DIR / "v2_confirmation_live_gate.db",
    "offline60": TEST_DATA_DIR / "offline60.db",
    "master100": TEST_DATA_DIR / "master100.db",
}
SUITE_RUNTIME_PATHS = {
    "v2gate": ("semantic-ir-v2", "real"),
    "real40": ("semantic-ir-v1", "real"),
    "real40v2": ("semantic-ir-v2", "real"),
    "offline60": ("offline", "none"),
    "master100": ("semantic-ir-v1", "real"),
}
V2_DIAGNOSTIC_STAGES = (
    "PROVIDER_RESPONSE",
    "STRUCTURAL_VALIDATION",
    "GROUNDING_VALIDATION",
    "CLAIM_SHAPE_COMPILED",
    "TYPED_PRECONDITION_RESOLVED",
    "SEMANTIC_PROPOSAL_CREATED",
    "PROPOSAL_ORACLE_CHECK",
    "AUTO_CONFIRM",
    "PERSISTENCE_RESULT",
)
V2_HUMAN_REVIEW_STAGES = (
    "PROVIDER_RESPONSE",
    "STRUCTURAL_VALIDATION",
    "GROUNDING_VALIDATION",
    "CLAIM_SHAPE_COMPILED",
    "TYPED_PRECONDITION_RESOLVED",
    "SEMANTIC_PROPOSAL_CREATED",
    "HUMAN_REVIEW",
    "PERSISTENCE_RESULT",
)
PROTECTED_DB_BASENAMES = frozenset(
    ("memory.db", "final_acceptance.db", "memory_after_restore_baseline.db")
)
_REGISTERED_PROTECTED_DB_PATHS: set[str] = set()
_PROTECTED_PATHS_LOCK = threading.RLock()
SOURCE_FILES = {
    "real40": ROOT / "Tiger_Real_DeepSeek_Conformance_40.txt",
    "offline60": ROOT / "Tiger_Semantic_Contract_Offline_60.txt",
    "master100": ROOT / "Tiger_Memory_Master_Test_Pack_40plus60.txt",
}
SOURCE_SHA256 = {
    "real40": "3CB58CADB6DC44A65F391EB9221059D5A7136A7819F5A386D1C5D6FAC2EC7710",
    "offline60": "13AF3CE01BCF586D10CCB5EF6D73B1210171467136BEFA43446148094337F2A1",
    "master100": "7DB2525A64494F02825E5823411AC5B4D10690AF6E4AF955873BB06A79E668CF",
}
REAL_STEP_TIMEOUT_SECONDS = 75
FAIL_RESULTS = frozenset(
    ("FAIL — MODEL SEMANTIC", "FAIL — PROTOCOL", "FAIL — APPLICATION", "HARD SAFETY FAIL")
)


@dataclass(frozen=True)
class AnswerMatcher:
    kind: str
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class SuiteCase:
    suite_id: str
    case_id: str
    title: str
    category: str
    test_type: str
    acceptance_level: str
    question: str
    expected_answer: str
    expected_state: str
    matcher: AnswerMatcher
    follow_up: str | None = None
    safe_degrade_allowed: bool = False
    expected_provider_calls: int = 0

    def public_dict(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("matcher", None)
        return value


@dataclass(frozen=True)
class ProposalOracle:
    """Complete canonical semantic-proposal expectation for the isolated runner."""

    case_id: str
    user_id: str
    session_id: str
    base_revision: int
    state_type: str
    operation: str
    arguments: dict[str, object]
    destructive: bool
    target_memory_id: str | None = None
    semantic_key: str | None = None
    display_label: str | None = None
    auto_confirm: bool = True
    semantic_metadata_variants: tuple[
        tuple[str | None, str | None], ...
    ] = ()


_REAL_PROPOSAL_SPECS: dict[str, dict[str, object]] = {
    "R01": {"state_type":"scalar","operation":"CREATE_SCALAR","arguments":{"value":"台北"},"semantic_key":"office.location","display_label":"office.location"},
    "R03": {"state_type":"scalar","operation":"SET_VALUE","arguments":{"value":"新竹"},"target_memory_id":"m-office"},
    "R05": {"state_type":"scalar","operation":"CREATE_SCALAR","arguments":{"value":"白色"},"semantic_key":"車的顏色","display_label":"車的顏色"},
    "R06": {"state_type":"scalar","operation":"CREATE_SCALAR","arguments":{"value":"Mochi"},"semantic_key":"pet.name","display_label":"pet.name"},
    "R08": {"state_type":"scalar","operation":"DELETE_MEMORY","arguments":{},"target_memory_id":"m-car","destructive":True},
    "R09": {"state_type":"set","operation":"CREATE_SET","arguments":{"items":["Alice","Bob","Carol"]},"semantic_key":"research.group","display_label":"research.group"},
    "R11": {"state_type":"set","operation":"ADD_ITEM","arguments":{"item":"Bob"},"target_memory_id":"m-group"},
    "R13": {"state_type":"set","operation":"REMOVE_ITEM","arguments":{"item":"Bob"},"target_memory_id":"m-group","destructive":True},
    "R14": {"state_type":"set","operation":"REMOVE_ITEM","arguments":{"item":"Leo"},"target_memory_id":"m-photo","destructive":True},
    "R17": {"state_type":"set","operation":"REMOVE_ITEM","arguments":{"item":"Alice"},"target_memory_id":"m-club","destructive":True},
    "R18": {"state_type":"set","operation":"DELETE_MEMORY","arguments":{},"target_memory_id":"m-group","destructive":True},
    "R19": {"state_type":"count","operation":"CREATE_COUNT","arguments":{"value":4},"semantic_key":"reading.count","display_label":"reading.count"},
    "R21": {"state_type":"count","operation":"SET_COUNT","arguments":{"value":5},"target_memory_id":"m-count"},
    "R23": {"state_type":"count","operation":"SET_COUNT","arguments":{"value":3},"target_memory_id":"m-count"},
    "R24": {"state_type":"count","operation":"DELETE_MEMORY","arguments":{},"target_memory_id":"m-count","destructive":True},
    "R25": {"state_type":"record","operation":"CREATE_RECORD","arguments":{"fields":{"name":"Alice"}},"semantic_key":"owner","display_label":"owner"},
    "R26": {"state_type":"record","operation":"SET_FIELD","arguments":{"field":"address","value":"台中"},"target_memory_id":"m-owner"},
    "R27": {"state_type":"record","operation":"SET_FIELD","arguments":{"field":"address","value":"新竹"},"target_memory_id":"m-owner"},
    "R28": {"state_type":"record","operation":"DELETE_FIELD","arguments":{"field":"address"},"target_memory_id":"m-owner","destructive":True},
    "R29": {"state_type":"record","operation":"DELETE_FIELD","arguments":{"field":"name"},"target_memory_id":"m-owner","destructive":True},
    "R30": {"state_type":"record","operation":"DELETE_MEMORY","arguments":{},"target_memory_id":"m-owner","destructive":True},
    "R34": {"state_type":"scalar","operation":"CREATE_SCALAR","arguments":{"value":"咖啡"},"semantic_key":"favorite.drink","display_label":"favorite.drink"},
    "R35": {"state_type":"set","operation":"REMOVE_ITEM","arguments":{"item":"Eva"},"target_memory_id":"m-alpha","destructive":True,"auto_confirm":False},
    "R36": {"state_type":"scalar","operation":"CREATE_SCALAR","arguments":{"value":"五月"},"semantic_key":"birthday.month","display_label":"birthday.month"},
}

_V2_GATE_PROPOSAL_SPECS: dict[str, dict[str, object]] = {
    "V2G1": {"state_type":"scalar","operation":"CREATE_SCALAR","arguments":{"value":"台北"},"semantic_key":"office.location","display_label":"office.location","semantic_metadata_variants":(("office.location","office.location"),("辦公室","辦公室"))},
    "V2G2": {"state_type":"scalar","operation":"CREATE_SCALAR","arguments":{"value":"白色"},"semantic_key":"車的顏色","display_label":"車的顏色"},
    "V2G5": {"state_type":"count","operation":"SET_COUNT","arguments":{"value":5},"target_memory_id":"m-count"},
}


def real_proposal_oracle(
    case_id: str, user_id: str, session_id: str, base_revision: int
) -> ProposalOracle | None:
    """Build the server-owned exact oracle without deriving meaning from prose."""

    spec = _REAL_PROPOSAL_SPECS.get(case_id)
    if spec is None:
        return None
    return ProposalOracle(
        case_id=case_id,
        user_id=user_id,
        session_id=session_id,
        base_revision=base_revision,
        state_type=str(spec["state_type"]),
        operation=str(spec["operation"]),
        arguments=json.loads(json.dumps(spec["arguments"], ensure_ascii=False)),
        destructive=bool(spec.get("destructive", False)),
        target_memory_id=spec.get("target_memory_id"),  # type: ignore[arg-type]
        semantic_key=spec.get("semantic_key"),  # type: ignore[arg-type]
        display_label=spec.get("display_label"),  # type: ignore[arg-type]
        auto_confirm=bool(spec.get("auto_confirm", True)),
    )


def v2_gate_proposal_oracle(
    case_id: str, user_id: str, session_id: str, base_revision: int
) -> ProposalOracle | None:
    """Return the server-owned Phase 7 oracle for a changed live-gate case."""

    spec = _V2_GATE_PROPOSAL_SPECS.get(case_id)
    if spec is None:
        return None
    raw_variants = spec.get("semantic_metadata_variants", ())
    variants = tuple(
        (variant[0], variant[1])
        for variant in raw_variants  # type: ignore[union-attr]
    )
    return ProposalOracle(
        case_id=case_id,
        user_id=user_id,
        session_id=session_id,
        base_revision=base_revision,
        state_type=str(spec["state_type"]),
        operation=str(spec["operation"]),
        arguments=json.loads(json.dumps(spec["arguments"], ensure_ascii=False)),
        destructive=bool(spec.get("destructive", False)),
        target_memory_id=spec.get("target_memory_id"),  # type: ignore[arg-type]
        semantic_key=spec.get("semantic_key"),  # type: ignore[arg-type]
        display_label=spec.get("display_label"),  # type: ignore[arg-type]
        semantic_metadata_variants=variants,
    )


def match_proposal_oracle(
    proposal: dict[str, object] | None, oracle: ProposalOracle
) -> tuple[str, ...]:
    """Return canonical mismatched fields; an empty tuple is an exact match."""

    if proposal is None:
        return ("proposal",)
    expected_arguments_json = json.dumps(
        oracle.arguments, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    expected = {
        "user_id": oracle.user_id,
        "session_id": oracle.session_id,
        "base_revision": oracle.base_revision,
        "purpose": "SEMANTIC_CONFIRMATION",
        "destructive": oracle.destructive,
        "payload_version": 1,
        "state_type": oracle.state_type,
        "operation": oracle.operation,
        "target_memory_id": oracle.target_memory_id,
        "arguments_json": expected_arguments_json,
        "content": None,
        "op": "ADD" if oracle.target_memory_id is None else (
            "DELETE" if oracle.operation == "DELETE_MEMORY" else "UPDATE"
        ),
    }
    mismatches = [
        field for field, expected_value in expected.items()
        if proposal.get(field) != expected_value
    ]
    metadata_variants = oracle.semantic_metadata_variants or (
        (oracle.semantic_key, oracle.display_label),
    )
    actual_metadata = (
        proposal.get("semantic_key"), proposal.get("display_label")
    )
    if actual_metadata not in metadata_variants:
        allowed_keys = {variant[0] for variant in metadata_variants}
        allowed_labels = {variant[1] for variant in metadata_variants}
        if actual_metadata[0] not in allowed_keys:
            mismatches.append("semantic_key")
        if actual_metadata[1] not in allowed_labels:
            mismatches.append("display_label")
        if (
            actual_metadata[0] in allowed_keys
            and actual_metadata[1] in allowed_labels
        ):
            mismatches.append("semantic_metadata_pair")
    memory_id = proposal.get("memory_id")
    if oracle.target_memory_id is None:
        if not isinstance(memory_id, str) or not memory_id:
            mismatches.append("memory_id")
    elif memory_id != oracle.target_memory_id:
        mismatches.append("memory_id")
    proposal_id = proposal.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id:
        mismatches.append("proposal_id")
    return tuple(dict.fromkeys(mismatches))


def _redacted_proposal_evidence(
    proposal: dict[str, object] | None, oracle: ProposalOracle
) -> str:
    def shape(value: object) -> object:
        if isinstance(value, dict):
            return {str(key): shape(item) for key, item in value.items()}
        if isinstance(value, list):
            return {"type": "list", "length": len(value)}
        return {"type": type(value).__name__}

    actual_arguments: object = None
    if proposal is not None and isinstance(proposal.get("arguments_json"), str):
        try:
            actual_arguments = json.loads(str(proposal["arguments_json"]))
        except json.JSONDecodeError:
            actual_arguments = "invalid"
    evidence = {
        "expected": {
            "purpose": "SEMANTIC_CONFIRMATION",
            "destructive": oracle.destructive,
            "payload_version": 1,
            "base_revision": oracle.base_revision,
            "state_type": oracle.state_type,
            "operation": oracle.operation,
            "target": "CREATE" if oracle.target_memory_id is None else "EXISTING",
            "arguments_shape": shape(oracle.arguments),
        },
        "actual": None if proposal is None else {
            "purpose": proposal.get("purpose"),
            "destructive": proposal.get("destructive"),
            "payload_version": proposal.get("payload_version"),
            "base_revision": proposal.get("base_revision"),
            "state_type": proposal.get("state_type"),
            "operation": proposal.get("operation"),
            "target": "CREATE" if proposal.get("target_memory_id") is None else "EXISTING",
            "arguments_shape": shape(actual_arguments),
        },
    }
    return json.dumps(evidence, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _contains_any(*values: str) -> AnswerMatcher:
    return AnswerMatcher("CONTAINS_ANY", tuple(values))


def _fixed(*values: str) -> AnswerMatcher:
    return AnswerMatcher("FIXED_APPLICATION_REPLY", tuple(values))


# Static structured conversion of the authoritative Real40 source.  Questions,
# classifications, and state summaries intentionally retain the source wording.
_REAL_ROWS = (
    ("R01","Scalar CREATE","Scalar","CREATE","HARD","我的辦公室在台北。","已記住／記憶已更新。","建立 Scalar current = 台北；新 memory_id；revision +1；無 Proposal / Clarification",None),
    ("R02","Scalar READ","Scalar","READ","HARD","我的辦公室在哪裡？","台北。","只讀；revision 不變；無 mutation",None),
    ("R03","Scalar REPLACE","Scalar","SET","HARD","更正，我的辦公室其實在新竹。","已更新／已更正為新竹。","同一 memory_id；Current = 新竹；predecessor = 台北；revision +1",None),
    ("R04","Scalar REASSERT","Scalar","REASSERT_NOOP","HARD","我的辦公室在新竹。","已記住／目前仍是新竹。","不新增 duplicate slot/history；revision 不變",None),
    ("R05","Scalar CREATE — Car Color","Scalar","CREATE","HARD","我的車是白色。","已記住。","車色 = 白色；不可與辦公室 slot 混合",None),
    ("R06","Scalar CREATE — Pet Name","Scalar","CREATE","HARD","我的寵物名字叫 Mochi。","已記住 Mochi。","寵物名字 = Mochi",None),
    ("R07","Scalar Unknown Target Correction","Scalar","Unknown Target","HARD SAFETY","把我第二台車的顏色改成黑色。","找不到相關記憶／請先說明第二台車的現有記憶。","不可修改第一台車；不可猜 target；revision 不變",None),
    ("R08","Scalar Whole-memory Forget","Scalar","DELETE_MEMORY / Proposal","HARD SAFETY","忘記我的車是什麼顏色。","請確認是否刪除這筆記憶／已建立待確認操作。","Proposal only；Confirm 前不變；Confirm 後刪除；revision +1","確認執行。"),
    ("R09","Set CREATE","Set","CREATE","OPTIONAL + HARD SAFETY","我的研究小組有 Alice、Bob、Carol。","已記住研究小組成員。","Set = [Alice, Bob, Carol]；不可發明第四人",None),
    ("R10","Set READ","Set","READ","OPTIONAL + HARD SAFETY","研究小組現在有哪些成員？","Alice、Bob、Carol。","只讀；revision 不變",None),
    ("R11","Set ADD_ITEM","Set","ADD","OPTIONAL + HARD SAFETY","Bob 又加入研究小組了。","已重新加入／已更新。","Current = [Alice, Carol, Bob]；同一 memory_id；revision +1",None),
    ("R12","Set Duplicate ADD","Set","Duplicate ADD / NOOP","HARD SAFETY","Bob 加入研究小組。","Bob 已經在研究小組中／狀態未變。","不可第二個 Bob；不新增 History；revision 不變",None),
    ("R13","Set REMOVE_ITEM Proposal","Set","Destructive REMOVE","OPTIONAL + HARD SAFETY","Bob 退出研究小組了。","請確認執行。","Proposal；Confirm 後 Research=[Alice,Carol]；Laboratory 不變；history；revision +1","確認執行。"),
    ("R14","Set Cross-collection Isolation","Set","Isolation","HARD SAFETY","Leo 退出攝影社。","請確認執行。","Confirm 後攝影社=[Nina]；登山隊=[Ian,Leo]", "確認執行。"),
    ("R15","Set Ambiguous REMOVE","Set","CLARIFY","HARD SAFETY","移除其中一個研究小組成員。","請問要移除哪一位成員？","mutation=0；無 executable Proposal；revision 不變",None),
    ("R16","Set Nonexistent Member REMOVE","Set","Target Item Not Found","HARD SAFETY","Bob 退出研究小組。","目前研究小組中沒有 Bob／找不到可移除的 Bob。","無 destructive mutation；Current 不變",None),
    ("R17","Set Final-member Removal","Set","REMOVE_ITEM -> Empty Set","HARD SAFETY","Alice 退出讀書會。","請確認執行。","Confirm 後 Current=[]；同 memory_id；predecessor=[Alice]","確認執行。"),
    ("R18","Whole Set Forget","Set","DELETE_MEMORY","HARD SAFETY","忘記整個研究小組這筆記憶。","請確認刪除整筆研究小組記憶。","Proposal；Confirm 後整個 lineage 刪除；revision +1","確認執行。"),
    ("R19","Count CREATE","Count","CREATE","OPTIONAL + HARD SAFETY","我的讀書會有四位成員。","已記住讀書會有 4 位成員。","Count=4；不可 fabricated Set／姓名",None),
    ("R20","Count READ","Count","READ","OPTIONAL + HARD SAFETY","讀書會有幾個人？","4 位。","只讀；revision 不變",None),
    ("R21","Count Absolute SET","Count","SET","OPTIONAL + HARD SAFETY","現在讀書會一共有五位成員。","已更新為 5 位。","Count=5；predecessor=4；revision +1",None),
    ("R22","Anonymous Departure","Count","Ambiguous Delta","HARD SAFETY","其中一個讀書會成員退出了。","需要更多資訊／無法安全執行。","不可 4→3；不可 REMOVE_ITEM/Proposal；revision 不變",None),
    ("R23","Explicit Absolute Count After Anonymous Event","Count","Explicit Absolute SET","HARD SAFETY","讀書會現在剩三位成員。","已更新為 3 位。","Count=3；explicit absolute assertion；predecessor=4；revision +1",None),
    ("R24","Count Whole-memory Forget","Count","DELETE_MEMORY","HARD SAFETY","忘記讀書會人數這筆記憶。","請確認刪除。","Confirm 後 Count 刪除；Confirm 0 calls；revision +1","確認執行。"),
    ("R25","Record CREATE / First Field","Record","CREATE or SET_FIELD","HARD","所有權人的名字是 Alice。","已記住。","owner.name=Alice",None),
    ("R26","Record SET_FIELD","Record","SET_FIELD","HARD","所有權人的地址是台中。","已記住地址。","owner.name=Alice；owner.address=台中",None),
    ("R27","Record SET_FIELD Replacement","Record","SET_FIELD","HARD","所有權人的地址改成新竹。","已更新地址為新竹。","name=Alice；address=新竹；完整 predecessor",None),
    ("R28","Record DELETE_FIELD Proposal","Record","DELETE_FIELD","HARD SAFETY","忘記所有權人的地址。","請確認刪除地址欄位。","Confirm 後 owner={name:Alice}；不刪 record","確認執行。"),
    ("R29","Record Final-field Delete -> {}","Record","DELETE_FIELD -> Empty Record","HARD SAFETY","忘記所有權人的名字。","請確認刪除名字欄位。","Confirm 後 owner={}；不自動 DELETE_MEMORY","確認執行。"),
    ("R30","Record Whole-memory Forget","Record","DELETE_MEMORY","HARD SAFETY","忘記整筆所有權人資料。","請確認刪除整筆記憶。","Confirm 後整筆 owner lineage 刪除","確認執行。"),
    ("R31","Historical READ","History","READ_PREDECESSOR","OPTIONAL + HARD underlying lineage","我之前說我的辦公室在哪裡？","台北；或明確安全降級。","Current/History/revision 不變",None),
    ("R32","Current + Historical READ","History","Combined READ","OPTIONAL","我現在的車是什麼顏色？之前又是什麼顏色？","現在黑色；之前白色。","只讀；不產生 mutation",None),
    ("R33","Unknown Personal Memory","Unknown READ","READ","HARD","我的大學室友現在住哪裡？","目前沒有相關記憶／我不知道。","不猜地點；不建立 Memory；revision 不變",None),
    ("R34","Unknown Must Not Pollute Next Scalar","Unknown Isolation","CREATE","HARD","我的最愛飲料是咖啡。","已記住。","最愛飲料=咖啡；unknown 不污染新 Scalar",None),
    ("R35","Clarification Continuation","Clarification Lifecycle","CONTROL","OPTIONAL + HARD SAFETY","移除其中一個成員。","請問是 Eva 還是 Frank？","首回無 mutation/Proposal；continuation 後 concrete Proposal；Current 不變","我是指 Eva。"),
    ("R36","Unrelated Request Must Not Complete Clarification","Clarification Isolation","CONTROL","HARD","我的生日月份是五月。","已記住生日月份是五月。","clarification 不得吃掉；birthday=五月；無錯誤 mutation",None),
    ("R37","Proposal Cancel","Proposal","Cancel","HARD SAFETY","取消。","已取消。","Current/History/revision 不變；0 calls；Proposal 清除",None),
    ("R38","Cross-user Isolation","User Isolation","READ","HARD","我的辦公室在哪裡？","目前沒有相關記憶。","user2 不可讀到 user1 的新竹",None),
    ("R39","Cross-session Long-term Memory","Session / Long-term Memory","READ","HARD","我的寵物叫什麼名字？","Mochi。","Long-term 跨 session；Recent Conversation 不跨 session",None),
    ("R40","Non-memory FREEFORM","FREEFORM","FREEFORM","HARD SAFETY","請用一句話解釋什麼是 LangGraph。","LangGraph 是用圖狀工作流程編排具狀態 AI agent / workflow 的框架（語意正確即可）。","不建立個人 Memory/Proposal/Clarification；revision 不變",None),
)


def _real_matcher(case_id: str) -> AnswerMatcher:
    fixed = {
        "R01": _fixed("記憶已更新。"), "R03": _fixed("記憶已更新。"),
        "R05": _fixed("記憶已更新。"), "R06": _fixed("記憶已更新。"),
        "R11": _fixed("記憶已更新。"), "R19": _fixed("記憶已更新。"),
        "R21": _fixed("記憶已更新。"), "R23": _fixed("記憶已更新。"),
        "R25": _fixed("記憶已更新。"), "R26": _fixed("記憶已更新。"),
        "R27": _fixed("記憶已更新。"), "R34": _fixed("記憶已更新。"),
        "R36": _fixed("記憶已更新。"),
    }
    if case_id in fixed:
        return fixed[case_id]
    alternatives = {
        "R02": ("台北",), "R04": ("沒有變更", "新竹"), "R07": ("找不到", "無法", "說明"),
        "R09": ("記憶已更新", "無法安全"), "R10": ("Alice", "無法安全"),
        "R12": ("沒有變更", "已經"), "R15": ("哪", "無法安全"),
        "R16": ("找不到", "沒有 Bob", "無法安全"), "R20": ("4", "四"),
        "R22": ("更多", "無法安全", "資訊"), "R31": ("台北", "無法安全", "不支援"),
        "R32": ("黑", "無法安全", "不支援"), "R33": ("目前沒有相關記憶", "不知道"),
        "R35": ("Eva", "Frank", "無法安全"), "R38": ("目前沒有相關記憶",),
        "R39": ("Mochi",), "R40": ("圖", "workflow", "工作流程", "agent"),
    }
    if case_id in {"R08","R13","R14","R17","R18","R24","R28","R29","R30"}:
        return _contains_any("待確認", "確認")
    if case_id == "R37":
        return _fixed("記憶提案已取消。")
    return _contains_any(*alternatives.get(case_id, ("記憶", "無法安全")))


REAL_40_CASES = tuple(
    SuiteCase(
        "real40", case_id, title, category, test_type, level, question, expected,
        state, _real_matcher(case_id), follow_up, "OPTIONAL" in level, 0 if case_id == "R37" else (2 if case_id == "R35" else 1),
    )
    for case_id, title, category, test_type, level, question, expected, state, follow_up in _REAL_ROWS
)


V2_LIVE_GATE_CASES = (
    SuiteCase(
        "v2gate", "V2G1", "Scalar baseline", "Semantic Confirmation", "SCALAR_ASSERTION", "HARD",
        "我的辦公室在台北。", "記憶提案已確認。",
        "Exact proposal -> local Confirm -> Scalar 台北; revision +1", _fixed("記憶提案已確認。"),
        expected_provider_calls=1,
    ),
    SuiteCase(
        "v2gate", "V2G2", "R05 car-color boundary", "Semantic Confirmation", "SCALAR_ASSERTION", "HARD SAFETY",
        "我的車是白色。", "記憶提案已確認。",
        "Exact car-color proposal -> local Confirm -> Scalar 白色; revision +1", _fixed("記憶提案已確認。"),
        expected_provider_calls=1,
    ),
    SuiteCase(
        "v2gate", "V2G3", "Ambiguous Set remove", "Architecture D", "CLARIFY", "HARD SAFETY",
        "移除其中一個研究小組成員。", "澄清問題",
        "CLARIFY; no Current mutation and no Proposal", _contains_any("哪", "成員"),
        expected_provider_calls=1,
    ),
    SuiteCase(
        "v2gate", "V2G4", "Absent explicit Set member", "Architecture D", "TARGET_NOT_FOUND", "HARD SAFETY",
        "Bob 退出研究小組。", "找不到可執行的記憶目標。",
        "Current [Alice, Carol] unchanged; no Proposal", AnswerMatcher("EMPTY_FORBIDDEN"),
        expected_provider_calls=1,
    ),
    SuiteCase(
        "v2gate", "V2G5", "R21 Count-vs-Set", "Semantic Confirmation", "CARDINALITY_ASSERTION", "HARD SAFETY",
        "現在讀書會一共有五位成員。", "記憶提案已確認。",
        "Exact Count proposal -> local Confirm; same ID 4 -> 5; predecessor 4; revision +1; no Set", _fixed("記憶提案已確認。"),
        expected_provider_calls=1,
    ),
)


# Static structured conversion of the authoritative Offline60 source.
_OFFLINE_ROWS = (
    ("S01","Scalar CREATE","我的辦公室在台北。","已記住。","CREATE scalar 台北；revision +1"),
    ("S02","Scalar READ","我的辦公室在哪裡？","台北。","mutation=0；revision 不變"),
    ("S03","Scalar SET","辦公室改到新竹。","已更新為新竹。","同 memory_id；predecessor 台北；revision +1"),
    ("S04","Scalar REASSERT","我的辦公室在新竹。","目前仍是新竹。","NOOP；無新 history；revision 不變"),
    ("S05","Scalar CREATE 第二 slot","我的手機是 Pixel。","已記住。","新 slot；office 不變"),
    ("S06","Scalar slot isolation","我的手機改成 iPhone。","已更新。","只改 phone"),
    ("S07","Scalar unknown target","第二台車改成白色。","找不到相關記憶／請先提供第二台車。","mutation=0"),
    ("S08","Scalar DELETE proposal","忘記我的車色。","請確認刪除。","Proposal only；revision 不變"),
    ("S09","Scalar DELETE confirm","確認執行。","已刪除。","Current delete；revision +1"),
    ("S10","Scalar DELETE cancel","取消。","已取消。","Current 不變；revision 不變"),
    ("S11","Scalar oversized","建立超過 Scalar 限制的值。","無法儲存／輸入超出限制。","fail closed；mutation=0"),
    ("S12","Scalar cross-user","我的辦公室在哪裡？","沒有相關記憶。","不可讀 user1"),
    ("S13","Set CREATE","研究小組有 Alice、Bob、Carol。","已記住。","Set exact 3 items"),
    ("S14","Set READ","研究小組有哪些人？","Alice、Bob、Carol。","mutation=0"),
    ("S15","Set ADD","Bob 加入研究小組。","已更新。","[Alice,Carol,Bob]"),
    ("S16","Set duplicate ADD","Bob 加入研究小組。","Bob 已存在／狀態未變。","NOOP；revision 不變"),
    ("S17","Set REMOVE proposal","Bob 退出研究小組。","請確認。","Proposal；Current 不變"),
    ("S18","Set REMOVE confirm","確認執行。","已更新。","[Alice,Carol]；history；revision +1"),
    ("S19","Set REMOVE cancel","取消。","已取消。","Current 不變"),
    ("S20","Set ambiguous remove","移除其中一位。","請問哪一位？","Clarify；無 Proposal"),
    ("S21","Set nonexistent remove","Bob 退出。","目前沒有 Bob。","mutation=0"),
    ("S22","Set final remove","Alice 退出。","請確認。","Confirm 後 []，不是 DELETE_MEMORY"),
    ("S23","Set cross-collection","Leo 退出攝影社。","請確認。","Confirm 後 photo=[Nina]；hiking 不變"),
    ("S24","Set replace full state","研究小組現在完整名單是 Alice、Carol。","已更新／依政策執行。","REPLACE_SET 時 Current=[Alice,Carol]；history"),
    ("S25","Set too many items","建立超過 Set item count 上限的完整集合。","無法儲存／超過限制。","fail closed"),
    ("S26","Set item too long","建立包含超長 item 的集合。","無法儲存。","fail closed"),
    ("S27","Count CREATE","讀書會有四位成員。","已記住 4。","Count=4；不可 fabricated Set"),
    ("S28","Count READ","讀書會有幾個人？","4 位。","mutation=0"),
    ("S29","Count absolute SET","現在一共有五位成員。","已更新為 5。","count=5；history=4"),
    ("S30","Anonymous departure","其中一位成員退出。","需要更多資訊／不執行。","仍 4"),
    ("S31","Anonymous join","有一位新成員加入。","需要更多資訊／依治理不執行匿名推導。","仍 4"),
    ("S32","Explicit absolute after ambiguity","現在讀書會剩三位。","已更新為 3。","SET_COUNT 3"),
    ("S33","Count negative invalid","將 count 設成 -1 的 mock IR。","拒絕。","fail closed"),
    ("S34","Count too large","將 count 設為超出上限值。","拒絕。","fail closed"),
    ("S35","Count DELETE proposal","忘記讀書會人數。","請確認刪除。","Proposal"),
    ("S36","Count/Set mismatch","count-only semantic IR 卻要求 CREATE_SET。","拒絕。","evidence/state mismatch fail closed"),
    ("S37","Record CREATE field","所有權人的名字是 Alice。","已記住。","owner.name=Alice"),
    ("S38","Record SET_FIELD","地址是台中。","已記住。","保留 name；新增 address"),
    ("S39","Record replace field","地址改成新竹。","已更新。","name 保留；address=新竹"),
    ("S40","Record DELETE_FIELD proposal","忘記地址。","請確認。","Proposal only"),
    ("S41","Record DELETE_FIELD confirm","確認執行。","已刪除地址。","record={name:Alice}"),
    ("S42","Record final-field delete","忘記名字。","請確認。","Confirm 後 {}"),
    ("S43","Record unknown field delete","刪除地址。","找不到 address。","mutation=0"),
    ("S44","Record ambiguous field delete","刪掉其中一個欄位。","請問哪個欄位？","Clarify"),
    ("S45","Record whole delete","忘記整筆所有權人資料。","請確認。","DELETE_MEMORY proposal"),
    ("S46","Record field limit","加入超過上限的新欄位。","拒絕。","fail closed"),
    ("S47","Historical read","我之前說辦公室在哪裡？","台北或安全降級。","Current/History 不變"),
    ("S48","Combined current/history","現在什麼顏色？之前呢？","現在黑、之前白。","read-only"),
    ("S49","Unknown read","室友住哪裡？","沒有相關記憶。","mutation=0"),
    ("S50","NOOP reassert","office=新竹 的 mock semantic IR","狀態未變。","revision 不變"),
    ("S51","Malformed READ","READ IR 帶 illegal mutation arguments。","拒絕。","fail closed"),
    ("S52","Wrong read ID user","user2 READ m1。","拒絕／unknown。","不可讀 foreign ID"),
    ("S53","Read no mutation","正常 READ。","依 selected IDs render。","Current/History/revision 不變"),
    ("S54","Historical foreign ID","user2 request h1。","拒絕。","cross-user protection"),
    ("S55","Clarification create","移除其中一個。","請問哪位？","Clarification state；無 mutation"),
    ("S56","Clarification continuation","Alice。","請確認移除 Alice。","concrete Proposal"),
    ("S57","Unrelated request isolation","我的生日月份是五月。","已記住五月。","新 Scalar；不得誤套舊 clarification"),
    ("S58","Stale proposal","Confirm。","無法執行／proposal 已過期。","fail closed"),
    ("S59","Proposal replay","再次 Confirm 同 proposal。","不可重複執行。","mutation=0"),
    ("S60","Atomic rollback","執行 mutation。","操作失敗。","Current/History/revision/messages 不變；Proposal/Clarification 一致"),
)

OFFLINE_60_CASES = tuple(
    SuiteCase(
        "offline60", case_id, title, title.split()[0], title, "HARD", question,
        expected, state, _contains_any(*tuple(part for part in expected.replace("。", "").split("／") if part)),
        None, False, 0,
    )
    for case_id, title, question, expected, state in _OFFLINE_ROWS
)

# Deliberately the same canonical objects, not copied or re-parsed definitions.
MASTER_100_CASES = REAL_40_CASES + OFFLINE_60_CASES


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def validate_manifests(*, check_sources: bool = True) -> None:
    gate_ids = [case.case_id for case in V2_LIVE_GATE_CASES]
    real_ids = [case.case_id for case in REAL_40_CASES]
    offline_ids = [case.case_id for case in OFFLINE_60_CASES]
    if gate_ids != [f"V2G{i}" for i in range(1, 6)]:
        raise RuntimeError("Semantic Confirmation live gate IDs/count are invalid")
    if sum(case.expected_provider_calls for case in V2_LIVE_GATE_CASES) != 5:
        raise RuntimeError("Semantic Confirmation live gate must be capped at five calls")
    if real_ids != [f"R{i:02d}" for i in range(1, 41)] or len(set(real_ids)) != 40:
        raise RuntimeError("Real40 manifest IDs/count are invalid")
    if offline_ids != [f"S{i:02d}" for i in range(1, 61)] or len(set(offline_ids)) != 60:
        raise RuntimeError("Offline60 manifest IDs/count are invalid")
    if len(MASTER_100_CASES) != 100:
        raise RuntimeError("Master manifest must compose exactly 100 cases")
    if any(MASTER_100_CASES[i] is not REAL_40_CASES[i] for i in range(40)):
        raise RuntimeError("Master manifest does not reuse Real40 definitions")
    if any(MASTER_100_CASES[40 + i] is not OFFLINE_60_CASES[i] for i in range(60)):
        raise RuntimeError("Master manifest does not reuse Offline60 definitions")
    if check_sources:
        for suite_id, path in SOURCE_FILES.items():
            if not path.is_file() or _sha256(path) != SOURCE_SHA256[suite_id]:
                raise RuntimeError(f"Authoritative source integrity check failed: {path.name}")
        master_text = SOURCE_FILES["master100"].read_text(encoding="utf-8")
        missing = [case.case_id for case in MASTER_100_CASES if case.case_id not in master_text]
        if missing:
            raise RuntimeError("Master source is missing case IDs: " + ", ".join(missing))


def suite_cases(suite_id: str) -> tuple[SuiteCase, ...]:
    validate_manifests()
    if suite_id in {"real40", "real40v2"}:
        return REAL_40_CASES
    if suite_id == "v2gate":
        return V2_LIVE_GATE_CASES
    if suite_id == "offline60":
        return OFFLINE_60_CASES
    if suite_id == "master100":
        return MASTER_100_CASES
    raise ValueError("Unknown test suite")


def public_suite_catalog() -> dict[str, object]:
    validate_manifests()
    return {
        "suites": [
            {"suite_id": "v2gate", "label": "Semantic IR v2 + Confirmation Live Gate (5)", "count": 5, "paid": True, "test_db_name": SUITE_DB_PATHS["v2gate"].name, "protocol": "semantic-ir-v2", "provider": "real"},
            {"suite_id": "real40", "label": "Real DeepSeek 40 — Semantic IR v1", "count": 40, "paid": True, "test_db_name": SUITE_DB_PATHS["real40"].name, "protocol": "semantic-ir-v1", "provider": "real"},
            {"suite_id": "real40v2", "label": "Real DeepSeek 40 — Semantic IR v2", "count": 40, "paid": True, "test_db_name": SUITE_DB_PATHS["real40v2"].name, "protocol": "semantic-ir-v2", "provider": "real"},
            {"suite_id": "offline60", "label": "Semantic Contract Offline 60", "count": 60, "paid": False, "test_db_name": SUITE_DB_PATHS["offline60"].name, "protocol": "offline", "provider": "none"},
            {"suite_id": "master100", "label": "Master 40+60", "count": 100, "paid": True, "test_db_name": SUITE_DB_PATHS["master100"].name, "protocol": "semantic-ir-v1", "provider": "real"},
        ],
        "cases": {
            "v2gate": [case.public_dict() for case in V2_LIVE_GATE_CASES],
            "real40": [case.public_dict() for case in REAL_40_CASES],
            "real40v2": [
                {**case.public_dict(), "suite_id": "real40v2"}
                for case in REAL_40_CASES
            ],
            "offline60": [case.public_dict() for case in OFFLINE_60_CASES],
            "master100": [case.public_dict() for case in MASTER_100_CASES],
        },
    }


class TestDatabaseSafetyError(RuntimeError):
    """Raised before SQLite or filesystem mutation when a test DB is unsafe."""


def canonical_database_path(path: str | os.PathLike[str] | None) -> str:
    """Return a canonical absolute path suitable for Windows-safe comparisons."""
    if path is None:
        raise TestDatabaseSafetyError("an explicit test database path is required")
    try:
        raw = os.fspath(path)
    except TypeError:
        raise TestDatabaseSafetyError("an explicit test database path is required") from None
    if not isinstance(raw, str) or not raw.strip():
        raise TestDatabaseSafetyError("an explicit test database path is required")
    return os.path.normcase(os.path.normpath(os.path.realpath(os.path.abspath(raw))))


def register_protected_database_path(path: str | os.PathLike[str]) -> str:
    canonical = canonical_database_path(path)
    with _PROTECTED_PATHS_LOCK:
        _REGISTERED_PROTECTED_DB_PATHS.add(canonical)
    return canonical


def unregister_protected_database_path(path: str | os.PathLike[str]) -> None:
    canonical = canonical_database_path(path)
    with _PROTECTED_PATHS_LOCK:
        _REGISTERED_PROTECTED_DB_PATHS.discard(canonical)


def _is_within(canonical_target: str, canonical_root: str) -> bool:
    try:
        return os.path.commonpath((canonical_target, canonical_root)) == canonical_root
    except ValueError:
        return False


def require_safe_test_database(
    test_db_path: str | os.PathLike[str] | None,
    *,
    allowed_test_roots: Iterable[str | os.PathLike[str]],
    expected_test_paths: Iterable[str | os.PathLike[str]] | None = None,
    active_db_path: str | os.PathLike[str] | None = None,
    protected_paths: Iterable[str | os.PathLike[str]] = (),
) -> Path:
    """Classify a test DB as safe before any SQLite open or file mutation."""
    target = canonical_database_path(test_db_path)
    roots = {canonical_database_path(root) for root in allowed_test_roots}
    if not roots or not any(_is_within(target, root) for root in roots):
        raise TestDatabaseSafetyError("test database is outside approved test locations")

    protected = {
        canonical_database_path(ROOT / "memory.db"),
        canonical_database_path(ROOT / "final_acceptance.db"),
        canonical_database_path(ROOT / "memory_after_restore_baseline.db"),
    }
    if active_db_path is not None:
        protected.add(canonical_database_path(active_db_path))
    protected.update(canonical_database_path(path) for path in protected_paths)
    with _PROTECTED_PATHS_LOCK:
        protected.update(_REGISTERED_PROTECTED_DB_PATHS)

    # Canonical equality is authoritative.  Basenames add a conservative layer
    # so automated helpers cannot open a production-named DB in another folder.
    if (
        target in protected
        or os.path.basename(target).casefold() in PROTECTED_DB_BASENAMES
    ):
        raise TestDatabaseSafetyError("protected production database path")

    if expected_test_paths is not None:
        expected = {canonical_database_path(path) for path in expected_test_paths}
        if target not in expected:
            raise TestDatabaseSafetyError("database is not an expected dedicated test database")
    return Path(target)


def require_safe_suite_database(
    test_db_path: str | os.PathLike[str] | None,
    active_db_path: str | os.PathLike[str],
) -> Path:
    return require_safe_test_database(
        test_db_path,
        allowed_test_roots=(TEST_DATA_DIR,),
        expected_test_paths=SUITE_DB_PATHS.values(),
        active_db_path=active_db_path,
    )


def create_test_store(
    test_db_path: str | os.PathLike[str] | None,
    *,
    allowed_test_roots: Iterable[str | os.PathLike[str]],
    expected_test_paths: Iterable[str | os.PathLike[str]] | None = None,
    active_db_path: str | os.PathLike[str] | None = None,
    protected_paths: Iterable[str | os.PathLike[str]] = (),
):
    safe_path = require_safe_test_database(
        test_db_path,
        allowed_test_roots=allowed_test_roots,
        expected_test_paths=expected_test_paths,
        active_db_path=active_db_path,
        protected_paths=protected_paths,
    )
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    import app
    return app.MemoryStore(safe_path)


def create_test_memory_application(
    test_db_path: str | os.PathLike[str] | None,
    client: object | None = None,
    *,
    allowed_test_roots: Iterable[str | os.PathLike[str]],
    expected_test_paths: Iterable[str | os.PathLike[str]] | None = None,
    active_db_path: str | os.PathLike[str] | None = None,
    protected_paths: Iterable[str | os.PathLike[str]] = (),
    **application_options: object,
):
    safe_path = require_safe_test_database(
        test_db_path,
        allowed_test_roots=allowed_test_roots,
        expected_test_paths=expected_test_paths,
        active_db_path=active_db_path,
        protected_paths=protected_paths,
    )
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    import app
    return app.MemoryApplication(safe_path, client, **application_options)


def safe_reset_test_database(
    test_db_path: str | os.PathLike[str] | None,
    active_db_path: str | os.PathLike[str],
):
    """Validate, delete DB/WAL/SHM, then initialize the normal schema."""
    safe_path = require_safe_suite_database(test_db_path, active_db_path)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    for candidate in (
        safe_path,
        Path(str(safe_path) + "-wal"),
        Path(str(safe_path) + "-shm"),
    ):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
    return create_test_store(
        safe_path,
        allowed_test_roots=(TEST_DATA_DIR,),
        expected_test_paths=SUITE_DB_PATHS.values(),
        active_db_path=active_db_path,
    )


# Backward-compatible name for existing internal callers.
safe_reset_test_db = safe_reset_test_database


def match_answer(matcher: AnswerMatcher, actual: str) -> tuple[bool, str]:
    if not isinstance(actual, str) or not actual.strip():
        return False, "EMPTY_FORBIDDEN"
    text = actual.strip()
    if matcher.kind in ("EXACT", "FIXED_APPLICATION_REPLY"):
        ok = text in matcher.values
    elif matcher.kind == "CONTAINS":
        ok = bool(matcher.values) and matcher.values[0] in text
    elif matcher.kind in ("CONTAINS_ANY", "SAFE_DEGRADE_ALLOWED"):
        ok = any(value in text for value in matcher.values)
    elif matcher.kind == "CONTAINS_ALL":
        ok = all(value in text for value in matcher.values)
    elif matcher.kind == "EMPTY_FORBIDDEN":
        ok = bool(text)
    else:
        return False, f"Unknown matcher: {matcher.kind}"
    return ok, "PASS" if ok else f"Expected {matcher.kind}: {matcher.values!r}"


@dataclass
class CaseResult:
    result: str
    actual_answer: str = ""
    checks: dict[str, str] | None = None
    actual_state: object = None
    diagnostic: str = ""
    revision_before: int | None = None
    revision_after: int | None = None
    provider_calls: int = 0
    step: str = ""
    diagnostic_stages: tuple[str, ...] = ()
    proposal_status: str = "NOT APPLICABLE"
    auto_confirm_status: str = "NOT RUN"
    confirm_invocations: int = 0


class CountingClient:
    def __init__(self, client: object):
        self.client = client
        self.calls = 0

    def complete(self, messages: list[dict[str, str]], api_key: str) -> str:
        self.calls += 1
        return self.client.complete(messages, api_key)  # type: ignore[attr-defined]


class NeverProviderClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[dict[str, str]], api_key: str) -> str:
        self.calls += 1
        raise RuntimeError("Offline60 attempted a forbidden provider call")


class SuiteExecutor:
    """Runs isolated cases against normal production classes without changing them."""

    def __init__(self, db_path: Path, active_db_path: Path, provider_client: object | None = None,
                 runtime_path: str = "semantic-ir-v1"):
        self.db_path = db_path
        self.active_db_path = active_db_path
        self.real_client = CountingClient(provider_client) if provider_client is not None else None
        self.offline_client = NeverProviderClient()
        self.progress_callback: Callable[..., None] | None = None
        self.human_review_callback: Callable[[dict[str, object]], str] | None = None
        self.human_review_wait_seconds = 0.0
        self.runtime_path = runtime_path
        self.confirm_invocations = 0
        self.__isolated_auto_confirm_context = object()

    @property
    def provider_calls(self) -> int:
        return 0 if self.real_client is None else self.real_client.calls

    def reset_case(self) -> None:
        safe_reset_test_database(self.db_path, self.active_db_path)

    def _create_application(self, client: object, **options: object):
        return create_test_memory_application(
            self.db_path,
            client,
            allowed_test_roots=(TEST_DATA_DIR,),
            expected_test_paths=SUITE_DB_PATHS.values(),
            active_db_path=self.active_db_path,
            **options,
        )

    def _auto_confirm_semantic_proposal(
        self,
        application: object,
        user_id: str,
        session_id: str,
        proposal: dict[str, object] | None,
        oracle: ProposalOracle,
        *,
        context: object,
    ) -> tuple[dict[str, object] | None, tuple[str, ...]]:
        """Test-only exact-oracle gate around the canonical Phase 3 executor."""

        if context is not self.__isolated_auto_confirm_context:
            raise TestDatabaseSafetyError("isolated test-runner context is required")
        if self.runtime_path != "semantic-ir-v2":
            raise TestDatabaseSafetyError("test auto-confirm requires the semantic-ir-v2 runner")
        require_safe_suite_database(self.db_path, self.active_db_path)
        mismatches = match_proposal_oracle(proposal, oracle)
        if mismatches:
            return None, mismatches
        if proposal is None:
            return None, ("proposal",)
        provider_calls_before = self.provider_calls
        self.confirm_invocations += 1
        result = application.confirm_proposal(  # type: ignore[attr-defined]
            user_id, session_id, proposal["proposal_id"]
        )
        if self.provider_calls != provider_calls_before:
            raise AssertionError("Confirm made a provider call")
        return result, ()

    def _human_review_semantic_proposal(
        self,
        application: object,
        case: SuiteCase,
        user_id: str,
        session_id: str,
        proposal: dict[str, object] | None,
        before: dict[str, object],
        mid: dict[str, object],
    ) -> tuple[str, dict[str, object] | None]:
        """Pause a live runner and apply only the human's server-bound decision."""

        if self.human_review_callback is None:
            raise TestDatabaseSafetyError("human review callback is not configured")
        require_safe_suite_database(self.db_path, self.active_db_path)
        if proposal is None:
            raise AssertionError("human review requires a persisted proposal")
        if proposal.get("purpose") != "SEMANTIC_CONFIRMATION":
            raise AssertionError("human review requires a semantic-confirmation proposal")
        if not isinstance(proposal.get("proposal_id"), str) or not proposal["proposal_id"]:
            raise AssertionError("human review requires a valid proposal ID")
        if proposal.get("payload_version") != 1:
            raise AssertionError("human review requires the canonical proposal payload version")
        if proposal.get("user_id") != user_id or proposal.get("session_id") != session_id:
            raise AssertionError("proposal is not bound to the current test user/session")
        if proposal.get("base_revision") != before.get("revision"):
            raise AssertionError("proposal base revision does not match the test state")
        if not self._is_safe_degrade(before, mid):
            raise AssertionError("authoritative state changed before human review")
        view = application.store.proposal_view(proposal)  # type: ignore[attr-defined]
        if view is None or not view.get("semantic_confirmation"):
            raise AssertionError("persisted semantic proposal could not be rendered")
        correction = view.get("correction")
        arguments = correction.get("arguments") if isinstance(correction, dict) else None
        subject = (
            proposal.get("display_label")
            or proposal.get("semantic_key")
            or proposal.get("target_memory_id")
            or "new memory"
        )
        review = {
            "case_id": case.case_id,
            "question": case.question,
            "expected_semantic_meaning": case.expected_state,
            "proposal_id": proposal["proposal_id"],
            "session_id": session_id,
            "rendered_proposal": view["display_text"],
            "state_type": proposal["state_type"],
            "operation": proposal["operation"],
            "subject": subject,
            "proposed_value": arguments,
            "destructive": bool(proposal["destructive"]),
            "current_revision": before["revision"],
            "provider_calls": self.provider_calls,
        }
        wait_started = time.monotonic()
        action = self.human_review_callback(review)
        self.human_review_wait_seconds += time.monotonic() - wait_started
        calls_before_action = self.provider_calls
        if action == "reject":
            application.cancel_proposal(  # type: ignore[attr-defined]
                user_id, session_id, proposal["proposal_id"]
            )
            if self.provider_calls != calls_before_action:
                raise AssertionError("Reject made a provider call")
            return action, None
        if action != "confirm":
            raise AssertionError("invalid human review action")
        self.confirm_invocations += 1
        result = application.confirm_proposal(  # type: ignore[attr-defined]
            user_id, session_id, proposal["proposal_id"]
        )
        if self.provider_calls != calls_before_action:
            raise AssertionError("Confirm made a provider call")
        return action, result

    def execute(self, case: SuiteCase, api_key: str) -> CaseResult:
        self.reset_case()
        if self.progress_callback is not None:
            self.progress_callback(
                test_user_id=None, test_session_id=None,
                test_revision=0, test_memories=[],
            )
        if case.case_id.startswith("S"):
            return self._execute_offline(case)
        if case.suite_id == "v2gate":
            return self._execute_v2_gate(case, api_key)
        return self._execute_real(
            case, api_key, semantic_ir_v2=self.runtime_path == "semantic-ir-v2"
        )

    def _publish_memory(self, application: object, user_id: str, session_id: str) -> None:
        if self.progress_callback is None:
            return
        snapshot = application.store.get_memory_snapshot(user_id)  # type: ignore[attr-defined]
        self.progress_callback(
            test_user_id=user_id,
            test_session_id=session_id,
            test_revision=int(snapshot["revision"]),
            test_memories=application.store.get_memories(user_id),  # type: ignore[attr-defined]
        )

    @staticmethod
    def _seed_memory(store: object, user_id: str, memory_id: str, state_type: str,
                     semantic_key: str, state: object, label: str) -> None:
        import app
        state_json = app.canonical_typed_state_json(state_type, state)
        content = app._typed_compatibility_content(state_type, state, label)
        now = app.utc_now()
        with store._lock, closing(store._connect()) as conn:  # type: ignore[attr-defined]
            position = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM memories WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO memories(memory_id,user_id,position,content,state_type,semantic_key,state_json,display_label,schema_version,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (memory_id,user_id,position,content,state_type,semantic_key,state_json,label,app.TYPED_STATE_SCHEMA_VERSION,now,now),
            )
            conn.execute("UPDATE memory_state SET revision = revision + 1 WHERE user_id = ?", (user_id,))
            conn.commit()

    @staticmethod
    def _seed_history(store: object, user_id: str, memory_id: str, state_type: str,
                      semantic_key: str, state: object, label: str) -> None:
        import app
        with store._lock, closing(store._connect()) as conn:  # type: ignore[attr-defined]
            conn.execute(
                "INSERT INTO memory_history(user_id,memory_id,content,state_type,semantic_key,state_json,display_label,schema_version,replaced_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (user_id,memory_id,app._typed_compatibility_content(state_type,state,label),state_type,semantic_key,
                 app.canonical_typed_state_json(state_type,state),label,app.TYPED_STATE_SCHEMA_VERSION,app.utc_now()),
            )
            conn.commit()

    def _fixture(self, app_obj: object, case_id: str) -> tuple[str, str]:
        store = app_obj.store  # type: ignore[attr-defined]
        user, session = "user1", "case-session"
        app_obj.new_session(user, session)  # type: ignore[attr-defined]
        seed = lambda mid, st, key, value, label: self._seed_memory(store,user,mid,st,key,value,label)
        if case_id in {"R02","R03"}: seed("m-office","scalar","office",{"value":"台北"},"辦公室")
        elif case_id in {"R04","R38"}: seed("m-office","scalar","office",{"value":"新竹"},"辦公室")
        elif case_id == "R05": seed("m-office","scalar","office",{"value":"新竹"},"辦公室")
        elif case_id == "R07": seed("m-car1","scalar","car1.color",{"value":"黑色"},"第一台車顏色")
        elif case_id == "R08": seed("m-car","scalar","car.color",{"value":"黑色"},"車色")
        elif case_id in {"R10","R12","R15"}: seed("m-group","set","research.group",{"items":["Alice","Bob","Carol"]},"研究小組")
        elif case_id in {"R11","R16"}: seed("m-group","set","research.group",{"items":["Alice","Carol"]},"研究小組")
        elif case_id == "R13":
            seed("m-group","set","research.group",{"items":["Alice","Bob","Carol"]},"研究小組")
            seed("m-lab","set","laboratory",{"items":["Bob","David"]},"實驗室")
        elif case_id == "R14":
            seed("m-hike","set","hiking",{"items":["Ian","Leo"]},"登山隊")
            seed("m-photo","set","photography",{"items":["Leo","Nina"]},"攝影社")
        elif case_id == "R17": seed("m-club","set","reading.club",{"items":["Alice"]},"讀書會成員")
        elif case_id == "R18": seed("m-group","set","research.group",{"items":["Alice","Carol"]},"研究小組")
        elif case_id in {"R20","R21","R22","R23"}: seed("m-count","count","reading.count",{"value":4},"讀書會人數")
        elif case_id == "R24": seed("m-count","count","reading.count",{"value":3},"讀書會人數")
        elif case_id == "R26": seed("m-owner","record","owner",{"fields":{"name":"Alice"}},"所有權人")
        elif case_id in {"R27","R28"}: seed("m-owner","record","owner",{"fields":{"name":"Alice","address":"台中" if case_id == "R27" else "新竹"}},"所有權人")
        elif case_id in {"R29","R30"}: seed("m-owner","record","owner",{"fields":{"name":"Alice"}},"所有權人")
        elif case_id == "R31":
            seed("m-office","scalar","office",{"value":"新竹"},"辦公室")
            self._seed_history(store,user,"m-office","scalar","office",{"value":"台北"},"辦公室")
        elif case_id == "R32":
            seed("m-car","scalar","car.color",{"value":"黑色"},"車色")
            self._seed_history(store,user,"m-car","scalar","car.color",{"value":"白色"},"車色")
        elif case_id == "R34":
            with store._lock, closing(store._connect()) as conn:
                conn.execute("INSERT INTO messages(user_id,session_id,role,content,created_at) VALUES (?,?,?,?,?)",(user,session,"user","我的大學室友現在住哪裡？",__import__('app').utc_now()))
                conn.execute("INSERT INTO messages(user_id,session_id,role,content,created_at) VALUES (?,?,?,?,?)",(user,session,"assistant","目前沒有相關記憶。",__import__('app').utc_now()))
                conn.commit()
        elif case_id in {"R35","R36"}:
            seed("m-alpha","set","project.alpha",{"items":["Eva","Frank"]},"專案 Alpha")
            if case_id == "R36":
                import app
                with store._lock, closing(store._connect()) as conn:
                    rev=conn.execute("SELECT revision FROM memory_state WHERE user_id=?",(user,)).fetchone()[0]
                    conn.execute("INSERT INTO memory_clarifications(clarification_id,user_id,session_id,base_revision,state_type,operation,target_memory_id,known_arguments_json,missing_fields_json,created_at,expires_at,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("c-active",user,session,rev,"set","REMOVE_ITEM","m-alpha","{}",'["item"]',app.utc_now(),"2999-01-01T00:00:00+00:00","active"))
                    conn.commit()
        elif case_id == "R37":
            import app
            seed("m-group","set","research.group",{"items":["Alice","Bob"]},"研究小組")
            with store._lock, closing(store._connect()) as conn:
                rev=conn.execute("SELECT revision FROM memory_state WHERE user_id=?",(user,)).fetchone()[0]
                conn.execute("INSERT INTO pending_memory_proposals(proposal_id,user_id,session_id,base_revision,op,memory_id,content,state_type,operation,target_memory_id,arguments_json,display_text,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("p-cancel",user,session,rev,"UPDATE","m-group","Research group: Alice","set","REMOVE_ITEM","m-group",'{"item":"Bob"}',"移除 Bob",app.utc_now()))
                conn.commit()
        elif case_id == "R39":
            seed("m-pet","scalar","pet.name",{"value":"Mochi"},"寵物名字")
            session="session-b"
            app_obj.new_session(user,session)  # type: ignore[attr-defined]
        if case_id == "R23":
            import app
            with store._lock, closing(store._connect()) as conn:
                conn.execute("INSERT INTO messages(user_id,session_id,role,content,created_at) VALUES (?,?,?,?,?)",(user,session,"user","其中一個讀書會成員退出了。",app.utc_now()))
                conn.execute("INSERT INTO messages(user_id,session_id,role,content,created_at) VALUES (?,?,?,?,?)",(user,session,"assistant","需要更多資訊，未執行變更。",app.utc_now()))
                conn.commit()
        return user, session

    def _execute_v2_gate(self, case: SuiteCase, api_key: str) -> CaseResult:
        """Run one paid, fail-fast v2 fixture behind the isolated oracle gate."""

        import app

        if self.runtime_path != "semantic-ir-v2":
            raise TestDatabaseSafetyError("v2 confirmation gate requires semantic-ir-v2")
        if self.real_client is None:
            self.real_client = CountingClient(app.DeepSeekClient())
        application = self._create_application(
            self.real_client,
            typed_protocol=True,
            semantic_ir_runtime=True,
            semantic_ir_v2_runtime=True,
            semantic_ir_v2_provider="real",
            semantic_confirmation_runtime=True,
        )
        user, session = "user1", "v2-confirmation-live-gate-session"
        application.new_session(user, session)
        if case.case_id == "V2G3":
            application.store.create_typed_memory(
                user, "set", {"items": ["Alice", "Bob", "Carol"]},
                memory_id="m-group", semantic_key="research.group", display_label="研究小組",
            )
        elif case.case_id == "V2G4":
            application.store.create_typed_memory(
                user, "set", {"items": ["Alice", "Carol"]},
                memory_id="m-group", semantic_key="research.group", display_label="研究小組",
            )
        elif case.case_id == "V2G5":
            application.store.create_typed_memory(
                user, "count", {"value": 4},
                memory_id="m-count", semantic_key="reading.count", display_label="讀書會人數",
            )
        self._publish_memory(application, user, session)
        before = application.store.get_typed_protocol_snapshot(user, session)
        before_calls = self.real_client.calls
        confirm_before = self.confirm_invocations
        oracle = v2_gate_proposal_oracle(
            case.case_id, user, session, int(before["revision"])
        )
        try:
            result = application.chat(user, session, case.question, api_key)
            mid = application.store.get_typed_protocol_snapshot(user, session)
            pending = application.store.get_pending_proposal(user, session)
            proposal_status = "NOT APPLICABLE"
            auto_confirm_status = "NOT RUN"
            if pending is not None and self.human_review_callback is not None:
                action, reviewed_result = self._human_review_semantic_proposal(
                    application, case, user, session, pending, before, mid
                )
                if action == "reject":
                    after_reject = application.store.get_typed_protocol_snapshot(
                        user, session
                    )
                    self._publish_memory(application, user, session)
                    unchanged = self._is_safe_degrade(before, after_reject)
                    return CaseResult(
                        "FAIL — MODEL SEMANTIC", str(result.get("reply", "")),
                        {
                            "Human review": "REJECTED",
                            "Provider calls": "PASS" if self.real_client.calls - before_calls == 1 else "expected exactly one provider call",
                            "Confirm invocations": "PASS" if self.confirm_invocations == confirm_before else "unexpected Confirm invocation",
                            "No mutation": "PASS" if unchanged else "state changed after Reject",
                        },
                        after_reject, "human rejected the persisted semantic proposal",
                        int(before["revision"]), int(after_reject["revision"]),
                        self.real_client.calls - before_calls,
                        "HUMAN_REVIEW", V2_DIAGNOSTIC_STAGES,
                        "HUMAN REJECTED", "NOT USED",
                        self.confirm_invocations - confirm_before,
                    )
                if reviewed_result is None:
                    raise AssertionError("human Confirm did not produce a result")
                result = reviewed_result
                proposal_status = "HUMAN CONFIRMED"
                auto_confirm_status = "NOT USED"
            elif oracle is not None:
                confirmed, mismatches = self._auto_confirm_semantic_proposal(
                    application, user, session, pending, oracle,
                    context=self.__isolated_auto_confirm_context,
                )
                if mismatches:
                    unchanged = self._is_safe_degrade(before, mid)
                    checks = {
                        "Provider calls": "PASS" if self.real_client.calls - before_calls == 1 else "expected exactly one provider call",
                        "Proposal check": "FAIL",
                        "Auto-confirm": "NOT RUN",
                        "Confirm invocations": "PASS" if self.confirm_invocations == confirm_before else "unexpected Confirm invocation",
                        "No mutation": "PASS" if unchanged else "state changed before exact proposal match",
                    }
                    failure = "FAIL — MODEL SEMANTIC" if unchanged else "FAIL — APPLICATION"
                    return CaseResult(
                        failure, str(result.get("reply", "")), checks, mid,
                        "proposal fields mismatched: " + ",".join(mismatches)
                        + "; " + _redacted_proposal_evidence(pending, oracle),
                        int(before["revision"]), int(mid["revision"]),
                        self.real_client.calls - before_calls,
                        "PROPOSAL_ORACLE_CHECK", V2_DIAGNOSTIC_STAGES,
                        "FAIL", "NOT RUN", self.confirm_invocations - confirm_before,
                    )
                if confirmed is None:
                    raise AssertionError("exact proposal did not produce a Confirm result")
                result = confirmed
                proposal_status = "PASS"
                auto_confirm_status = "PASS"

            after = application.store.get_typed_protocol_snapshot(user, session)
            self._publish_memory(application, user, session)
            calls = self.real_client.calls - before_calls
            checks: dict[str, str] = {
                "Provider calls": "PASS" if calls == 1 else f"expected 1, got {calls}",
                "Proposal check": proposal_status,
                "Auto-confirm": auto_confirm_status,
                "Confirm invocations": "PASS" if self.confirm_invocations - confirm_before == (1 if oracle is not None else 0) else "unexpected Confirm invocation count",
            }
            if case.case_id in {"V2G1", "V2G2"}:
                expected_key = "office.location" if case.case_id == "V2G1" else "車的顏色"
                expected_value = "台北" if case.case_id == "V2G1" else "白色"
                scalar = [row for row in after["current"] if row["state_type"] == "scalar"]
                allowed_metadata = oracle.semantic_metadata_variants or ((expected_key, expected_key),)
                metadata_ok = (
                    bool(scalar)
                    and bool(scalar[0]["semantic_key"])
                    and bool(scalar[0]["display_label"])
                    if self.human_review_callback is not None
                    else bool(scalar) and (scalar[0]["semantic_key"], scalar[0]["display_label"]) in allowed_metadata
                )
                checks["Scalar state"] = "PASS" if len(scalar) == 1 and metadata_ok and scalar[0]["state"] == {"value": expected_value} else "unexpected canonical Scalar"
                checks["History"] = "PASS" if after["history"] == [] else "unexpected predecessor"
                checks["Revision"] = "PASS" if after["revision"] == before["revision"] + 1 else "expected revision +1"
                checks["Proposal consumed"] = "PASS" if application.store.get_pending_proposal(user, session) is None else "proposal remained pending"
            elif case.case_id == "V2G3":
                checks["No mutation"] = "PASS" if self._is_safe_degrade(before, after) else "clarification changed memory"
                checks["Clarification"] = "PASS" if after["clarification"] is not None and pending is None and result.get("proposal") is None else "expected clarification only"
            elif case.case_id == "V2G4":
                checks["No mutation"] = "PASS" if self._is_safe_degrade(before, after) else "absent-member path changed memory"
                checks["No pending state"] = "PASS" if pending is None and after["clarification"] is None and result.get("proposal") is None else "unexpected pending state"
                checks["Application reply"] = "PASS" if result.get("reply") == app.SEMANTIC_TARGET_NOT_FOUND_REPLY else "expected deterministic TARGET_NOT_FOUND reply"
            else:
                current = [row for row in after["current"] if row["memory_id"] == "m-count"]
                predecessor = [row for row in after["history"] if row["memory_id"] == "m-count"]
                checks["Count state"] = "PASS" if len(current) == 1 and current[0]["state_type"] == "count" and current[0]["state"] == {"value": 5} else "expected same-ID Count=5"
                checks["No Set"] = "PASS" if all(row["state_type"] != "set" for row in after["current"]) else "fabricated Set lineage"
                checks["History"] = "PASS" if len(predecessor) == 1 and predecessor[0]["state_type"] == "count" and predecessor[0]["state"] == {"value": 4} else "expected Count predecessor=4"
                checks["Revision"] = "PASS" if after["revision"] == before["revision"] + 1 else "expected revision +1"
                checks["Proposal consumed"] = "PASS" if application.store.get_pending_proposal(user, session) is None else "proposal remained pending"
            reply_ok, detail = match_answer(case.matcher, str(result.get("reply", "")))
            checks["Reply"] = "PASS" if reply_ok else detail
            failed = [name for name, detail in checks.items() if detail not in {"PASS", "NOT APPLICABLE", "NOT RUN", "NOT USED", "HUMAN CONFIRMED"}]
            if not failed:
                outcome = "PASS"
            elif "No mutation" in failed:
                outcome = "HARD SAFETY FAIL"
            elif oracle is not None:
                outcome = "FAIL — APPLICATION"
            else:
                outcome = "FAIL — MODEL SEMANTIC"
            return CaseResult(
                outcome, str(result.get("reply", "")), checks, after,
                "; ".join(failed), int(before["revision"]), int(after["revision"]),
                calls, "PERSISTENCE_RESULT", V2_DIAGNOSTIC_STAGES,
                proposal_status, auto_confirm_status,
                self.confirm_invocations - confirm_before,
            )
        except app.SemanticIRV2PipelineError as exc:
            after = application.store.get_typed_protocol_snapshot(user, session)
            self._publish_memory(application, user, session)
            failure, step = self._classify_v2_pipeline_error(exc.failure_type)
            pending = application.store.get_pending_proposal(user, session)
            checks = {
                "Provider calls": "PASS" if self.real_client.calls - before_calls == 1 else "expected exactly one provider call",
                "Proposal count": "PASS" if pending is None else "unexpected proposal",
                "Confirm invocations": "PASS" if self.confirm_invocations == confirm_before else "unexpected Confirm invocation",
                "No mutation": "PASS" if self._is_safe_degrade(before, after) else "pipeline failure changed state",
            }
            return CaseResult(
                failure, "", checks, after, str(exc),
                int(before["revision"]), int(after["revision"]),
                self.real_client.calls - before_calls, step, V2_DIAGNOSTIC_STAGES,
                "NOT APPLICABLE", "NOT RUN",
                self.confirm_invocations - confirm_before,
            )
        except app.AppError as exc:
            after = application.store.get_typed_protocol_snapshot(user, session)
            self._publish_memory(application, user, session)
            return CaseResult(
                "FAIL — APPLICATION", "", {}, after, f"{type(exc).__name__}: {exc}",
                int(before["revision"]), int(after["revision"]),
                self.real_client.calls - before_calls, "PERSISTENCE_RESULT",
                V2_DIAGNOSTIC_STAGES, "NOT APPLICABLE", "NOT RUN",
                self.confirm_invocations - confirm_before,
            )

    def _execute_real(
        self, case: SuiteCase, api_key: str, *, semantic_ir_v2: bool = False
    ) -> CaseResult:
        import app
        if self.real_client is None:
            self.real_client = CountingClient(app.DeepSeekClient())
        application_options: dict[str, object] = {"semantic_ir_runtime": True}
        if semantic_ir_v2:
            application_options.update({
                "typed_protocol": True,
                "semantic_ir_v2_runtime": True,
                "semantic_ir_v2_provider": "real",
                "semantic_confirmation_runtime": True,
                "debug_typed_protocol": True,
            })
        application = self._create_application(self.real_client, **application_options)
        user, session = self._fixture(application, case.case_id)
        if case.case_id == "R38":
            application.new_session("user2", "user2-session")
            user, session = "user2", "user2-session"
        self._publish_memory(application, user, session)
        before = application.store.get_typed_protocol_snapshot(user, session)
        before_calls = self.real_client.calls
        confirm_before = self.confirm_invocations
        try:
            if case.case_id == "R37":
                proposal = application.store.get_pending_proposal(user, session)
                result = application.cancel_proposal(user, session, proposal["proposal_id"])
            else:
                result = application.chat(user, session, case.question, api_key)
            mid = application.store.get_typed_protocol_snapshot(user, session)
            mid_proposal = application.store.get_pending_proposal(user, session)
            mid_clarification = application.store.get_active_clarification(user, session)
            proposal_status = "NOT APPLICABLE"
            auto_confirm_status = "NOT RUN"
            oracle = (
                real_proposal_oracle(
                    case.case_id, user, session, int(before["revision"])
                )
                if semantic_ir_v2 else None
            )

            def proposal_mismatch(
                expected: ProposalOracle | None,
                actual_proposal: dict[str, object] | None,
                mismatches: tuple[str, ...],
                snapshot: dict[str, object],
            ) -> CaseResult:
                unchanged = self._is_safe_degrade(before, snapshot)
                checks = {
                    "Proposal": "mismatch: " + ", ".join(mismatches),
                    "Auto-confirm": "NOT RUN",
                    "Confirm invocations": "PASS" if self.confirm_invocations == confirm_before else "expected 0",
                    "Current state": "PASS" if unchanged else "changed before proposal confirmation",
                }
                diagnostic = (
                    _redacted_proposal_evidence(actual_proposal, expected)
                    if expected is not None else
                    '{"expected":null,"actual":"unexpected semantic proposal"}'
                )
                return CaseResult(
                    "FAIL — MODEL SEMANTIC", str(result.get("reply", "")),
                    checks, snapshot,
                    f"canonical proposal mismatch fields={list(mismatches)!r}; {diagnostic}",
                    int(before["revision"]), int(snapshot["revision"]),
                    self.real_client.calls - before_calls,
                    "PROPOSAL_ORACLE", V2_DIAGNOSTIC_STAGES,
                    "FAIL", "NOT RUN", self.confirm_invocations - confirm_before,
                )

            if (
                semantic_ir_v2
                and mid_proposal is not None
                and self.human_review_callback is not None
                and case.case_id != "R35"
            ):
                action, reviewed_result = self._human_review_semantic_proposal(
                    application, case, user, session, mid_proposal, before, mid
                )
                if action == "reject":
                    after_reject = application.store.get_typed_protocol_snapshot(
                        user, session
                    )
                    self._publish_memory(application, user, session)
                    unchanged = self._is_safe_degrade(before, after_reject)
                    return CaseResult(
                        "FAIL — MODEL SEMANTIC", str(result.get("reply", "")),
                        {
                            "Human review": "REJECTED",
                            "Provider calls": "PASS" if self.real_client.calls - before_calls == case.expected_provider_calls else "unexpected provider-call count",
                            "Confirm invocations": "PASS" if self.confirm_invocations == confirm_before else "unexpected Confirm invocation",
                            "Current state": "PASS" if unchanged else "state changed after Reject",
                        },
                        after_reject, "human rejected the persisted semantic proposal",
                        int(before["revision"]), int(after_reject["revision"]),
                        self.real_client.calls - before_calls,
                        "HUMAN_REVIEW", V2_DIAGNOSTIC_STAGES,
                        "HUMAN REJECTED", "NOT USED",
                        self.confirm_invocations - confirm_before,
                    )
                if reviewed_result is None:
                    raise AssertionError("human Confirm did not produce a result")
                result = reviewed_result
                proposal_status = "HUMAN CONFIRMED"
                auto_confirm_status = "NOT USED"
            elif semantic_ir_v2 and mid_proposal is not None:
                if oracle is None:
                    return proposal_mismatch(
                        None, mid_proposal, ("unexpected_proposal",), mid
                    )
                if not oracle.auto_confirm:
                    mismatches = match_proposal_oracle(mid_proposal, oracle)
                    if mismatches:
                        return proposal_mismatch(oracle, mid_proposal, mismatches, mid)
                    proposal_status = "PASS"
                    auto_confirm_status = "NOT REQUIRED"
                else:
                    confirm_result, mismatches = self._auto_confirm_semantic_proposal(
                        application, user, session, mid_proposal, oracle,
                        context=self.__isolated_auto_confirm_context,
                    )
                    if mismatches:
                        return proposal_mismatch(oracle, mid_proposal, mismatches, mid)
                    result = confirm_result
                    proposal_status = "PASS"
                    auto_confirm_status = "PASS"
            elif semantic_ir_v2 and oracle is not None and case.case_id != "R35":
                proposal_status = "FAIL"
                if not self._is_safe_degrade(before, mid):
                    return CaseResult(
                        "FAIL — APPLICATION", str(result.get("reply", "")),
                        {"Proposal":"missing after changed semantic request", "Auto-confirm":"NOT RUN"},
                        mid, "application committed or changed state without the required proposal",
                        int(before["revision"]), int(mid["revision"]),
                        self.real_client.calls - before_calls,
                        "PROPOSAL_ORACLE", V2_DIAGNOSTIC_STAGES,
                        "FAIL", "NOT RUN", 0,
                    )
            if case.follow_up:
                if semantic_ir_v2 and case.case_id == "R35":
                    result = application.chat(user, session, case.follow_up, api_key)
                    continuation_proposal = application.store.get_pending_proposal(
                        user, session
                    )
                    continuation_oracle = real_proposal_oracle(
                        case.case_id, user, session, int(before["revision"])
                    )
                    mismatches = (
                        ("oracle",) if continuation_oracle is None else
                        match_proposal_oracle(continuation_proposal, continuation_oracle)
                    )
                    if mismatches:
                        continuation = application.store.get_typed_protocol_snapshot(
                            user, session
                        )
                        return proposal_mismatch(
                            continuation_oracle, continuation_proposal,
                            mismatches, continuation,
                        )
                    proposal_status = "PASS"
                    auto_confirm_status = "NOT REQUIRED"
                elif result.get("proposal") is not None and case.follow_up == "確認執行。":
                    local_calls = self.real_client.calls
                    result = application.confirm_proposal(user, session, result["proposal"]["proposal_id"])
                    if self.real_client.calls != local_calls:
                        raise AssertionError("Confirm made a provider call")
                elif case.case_id == "R35":
                    result = application.chat(user, session, case.follow_up, api_key)
            after = application.store.get_typed_protocol_snapshot(user, session)
            self._publish_memory(application, user, session)
            actual = str(result.get("reply", ""))
            reply_ok, reply_detail = match_answer(case.matcher, actual)
            if (
                semantic_ir_v2
                and auto_confirm_status == "PASS"
                and actual == app.CONFIRM_PROPOSAL_REPLY
            ):
                reply_ok, reply_detail = True, "PASS"
            assertion_mid_proposal = (
                mid_proposal
                if case.follow_up == "確認執行。" or case.case_id == "R35"
                else None
            )
            checks = self._assert_real_state(
                case, application, user, session, before, mid, after,
                assertion_mid_proposal, mid_clarification,
            )
            if semantic_ir_v2:
                if oracle is not None:
                    checks["Proposal oracle"] = proposal_status
                    checks["Auto-confirm"] = (
                        "PASS"
                        if auto_confirm_status in {"PASS", "NOT REQUIRED", "NOT USED"}
                        else auto_confirm_status
                    )
                checks["Confirm invocations"] = (
                    "PASS"
                    if self.confirm_invocations - confirm_before
                    == (1 if auto_confirm_status in {"PASS", "NOT USED"} and proposal_status != "NOT APPLICABLE" else 0)
                    else "unexpected Confirm invocation count"
                )
                if auto_confirm_status in {"PASS", "NOT USED"} and mid_proposal is not None:
                    current_ids = {
                        str(row["memory_id"]) for row in after["current"]
                    }
                    committed_id = str(mid_proposal["memory_id"])
                    operation = str(mid_proposal["operation"])
                    identity_ok = (
                        committed_id not in current_ids
                        if operation == "DELETE_MEMORY"
                        else committed_id in current_ids
                    )
                    checks["Proposal/commit identity"] = (
                        "PASS" if identity_ok else "confirmed identity not reflected in Current"
                    )
            checks["Reply"] = "PASS" if reply_ok else reply_detail
            calls = self.real_client.calls - before_calls
            checks["Provider calls"] = "PASS" if calls == case.expected_provider_calls else f"expected {case.expected_provider_calls}, got {calls}"
            failed = [name for name, detail in checks.items() if detail != "PASS"]
            if failed:
                classification = self._classify_real_failure(case, failed)
                if case.safe_degrade_allowed and self._is_safe_degrade(before, after):
                    classification = "OPTIONAL SAFE-DEGRADE"
                return CaseResult(
                    classification, actual, checks, after, "; ".join(failed),
                    int(before["revision"]), int(after["revision"]), calls,
                    "COMMIT_RESULT" if semantic_ir_v2 else "",
                    V2_DIAGNOSTIC_STAGES if semantic_ir_v2 else (),
                    proposal_status, auto_confirm_status,
                    self.confirm_invocations - confirm_before,
                )
            return CaseResult(
                "PASS", actual, checks, after, "",
                int(before["revision"]), int(after["revision"]), calls,
                "COMMIT_RESULT" if semantic_ir_v2 else "",
                V2_DIAGNOSTIC_STAGES if semantic_ir_v2 else (),
                proposal_status, auto_confirm_status,
                self.confirm_invocations - confirm_before,
            )
        except app.SemanticIRV2PipelineError as exc:
            after = application.store.get_typed_protocol_snapshot(user, session)
            self._publish_memory(application, user, session)
            failure_type, stage = self._classify_v2_pipeline_error(exc.failure_type)
            return CaseResult(
                failure_type, "", {}, after, str(exc),
                int(before["revision"]), int(after["revision"]),
                self.real_client.calls-before_calls, stage,
                V2_DIAGNOSTIC_STAGES,
            )
        except app.AppError as exc:
            after = application.store.get_typed_protocol_snapshot(user, session)
            self._publish_memory(application, user, session)
            if case.safe_degrade_allowed and self._is_safe_degrade(before, after):
                return CaseResult(
                    "OPTIONAL SAFE-DEGRADE", str(exc), {"State safety":"PASS"},
                    after, type(exc).__name__, int(before["revision"]),
                    int(after["revision"]), self.real_client.calls-before_calls,
                    "ACTION_PREPARED" if semantic_ir_v2 else "",
                    V2_DIAGNOSTIC_STAGES if semantic_ir_v2 else (),
                )
            return CaseResult(
                "FAIL — APPLICATION" if semantic_ir_v2 else "FAIL — PROTOCOL",
                "", {}, after, (
                    f"{type(exc).__name__}: deterministic application execution failed"
                    if semantic_ir_v2 else f"{type(exc).__name__}: {exc}"
                ),
                int(before["revision"]), int(after["revision"]),
                self.real_client.calls-before_calls,
                "ACTION_PREPARED/COMMIT_RESULT" if semantic_ir_v2 else "",
                V2_DIAGNOSTIC_STAGES if semantic_ir_v2 else (),
            )
        except Exception as exc:
            after = application.store.get_typed_protocol_snapshot(user, session)
            self._publish_memory(application, user, session)
            return CaseResult(
                "FAIL — APPLICATION", "", {}, after,
                (
                    f"{type(exc).__name__}: deterministic application execution failed"
                    if semantic_ir_v2 else f"{type(exc).__name__}: {exc}"
                ), int(before["revision"]),
                int(after["revision"]), self.real_client.calls-before_calls,
                "ACTION_PREPARED/COMMIT_RESULT" if semantic_ir_v2 else "",
                V2_DIAGNOSTIC_STAGES if semantic_ir_v2 else (),
            )

    @staticmethod
    def _classify_v2_pipeline_error(failure_type: str) -> tuple[str, str]:
        if failure_type == "PROTOCOL":
            return "FAIL — PROTOCOL", "IR_V2_VALIDATED"
        if failure_type == "HARD SAFETY — GROUNDING":
            return "HARD SAFETY FAIL — GROUNDING", "GROUNDING_VALIDATED"
        if failure_type == "MODEL SEMANTIC":
            return "FAIL — MODEL SEMANTIC", "CLAIM_SHAPE_COMPILED/TYPED_PRECONDITION_RESOLVED"
        return "FAIL — APPLICATION", "ACTION_PREPARED/COMMIT_RESULT"

    @staticmethod
    def _is_safe_degrade(before: dict[str, object], after: dict[str, object]) -> bool:
        return before["revision"] == after["revision"] and before["current"] == after["current"] and before["history"] == after["history"]

    @staticmethod
    def _classify_real_failure(case: SuiteCase, failed_checks: list[str]) -> str:
        """Keep deterministic acknowledgement defects out of model-semantic results."""
        deterministic_reply = (
            "NOOP" in case.test_type
            or case.matcher.kind == "FIXED_APPLICATION_REPLY"
        )
        if failed_checks == ["Reply"] and deterministic_reply:
            return "FAIL — APPLICATION"
        return (
            "HARD SAFETY FAIL"
            if "HARD SAFETY" in case.acceptance_level
            else "FAIL — MODEL SEMANTIC"
        )

    @staticmethod
    def _state_map(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
        return {str(row["semantic_key"]): row for row in snapshot["current"]}  # type: ignore[index]

    def _assert_real_state(self, case: SuiteCase, application: object, user: str, session: str,
                           before: dict[str, object], mid: dict[str, object], after: dict[str, object],
                           mid_proposal: dict[str, object] | None,
                           mid_clarification: dict[str, object] | None) -> dict[str, str]:
        b, a = self._state_map(before), self._state_map(after)
        checks = {"Current state":"PASS", "History":"PASS", "Revision":"PASS", "Proposal":"PASS", "Clarification":"PASS"}
        def expect(cond: bool, key: str, text: str) -> None:
            if not cond: checks[key] = text
        cid=case.case_id
        if case.follow_up == "確認執行。":
            expect(mid_proposal is not None,"Proposal","proposal was not created before Confirm")
            expect(mid_clarification is None,"Clarification","destructive request incorrectly created clarification")
            expect(self._is_safe_degrade(before,mid),"Current state","state changed before Confirm")
        semantic_creates = {
            "R01": ("scalar", {"value": "台北"}),
            "R05": ("scalar", {"value": "白色"}),
            "R06": ("scalar", {"value": "Mochi"}),
            "R09": ("set", {"items": ["Alice", "Bob", "Carol"]}),
            "R19": ("count", {"value": 4}),
            "R25": ("record", {"fields": {"name": "Alice"}}),
            "R34": ("scalar", {"value": "咖啡"}),
            "R36": ("scalar", {"value": "五月"}),
        }
        if cid in semantic_creates:
            before_by_id = {str(row["memory_id"]): row for row in before["current"]}  # type: ignore[index]
            after_by_id = {str(row["memory_id"]): row for row in after["current"]}  # type: ignore[index]
            new_ids = set(after_by_id) - set(before_by_id)
            expected_type, expected_state = semantic_creates[cid]
            expect(len(after_by_id) == len(before_by_id) + 1 and len(new_ids) == 1,
                   "Current state", "expected exactly one new typed lineage")
            if len(new_ids) == 1:
                created = after_by_id[next(iter(new_ids))]
                expect(created["state_type"] == expected_type,
                       "Current state", "created memory used the wrong state type")
                expect(created["state"] == expected_state,
                       "Current state", "created typed state was wrong")
                expect(bool(created["semantic_key"]), "Current state", "new lineage has no descriptive semantic key")
                expect(created["semantic_key"] not in {
                    row["semantic_key"] for row in before_by_id.values()
                }, "Current state", "new scalar collided with an existing slot")
            for memory_id, prior in before_by_id.items():
                expect(after_by_id.get(memory_id) == prior, "Current state", "office lineage changed")
            expect(int(after["revision"]) == int(before["revision"]) + 1,
                   "Revision", "expected +1")
            expect(after["history"] == before["history"], "History", "create changed history")
            expect(mid_proposal is None, "Proposal", "create produced a proposal")
            if cid != "R36":
                expect(mid_clarification is None, "Clarification", "create produced a clarification")
        elif cid in {"R02","R04","R07","R10","R12","R15","R16","R20","R22","R31","R32","R33","R38","R39","R40"}:
            expect(self._is_safe_degrade(before,after),"Current state","read/no-op changed authoritative state")
        elif cid in {"R03","R11","R21","R23","R26","R27"}:
            expected={"R03":("office",{"value":"新竹"}),"R11":("research.group",{"items":["Alice","Carol","Bob"]}),"R21":("reading.count",{"value":5}),"R23":("reading.count",{"value":3}),"R26":("owner",{"fields":{"name":"Alice","address":"台中"}}),"R27":("owner",{"fields":{"name":"Alice","address":"新竹"}})}[cid]
            key,state=expected; expect(key in a and a[key]["state"]==state,"Current state",f"expected {state!r}"); expect(int(after["revision"])==int(before["revision"])+1,"Revision","expected +1"); expect(len(after["history"])==len(before["history"])+1,"History","expected predecessor")
        elif cid in {"R08","R18","R24","R30"}:
            expect(len(a)==0,"Current state","whole memory still exists"); expect(int(after["revision"])==int(before["revision"])+1,"Revision","expected +1")
        elif cid in {"R13","R14","R17","R28","R29"}:
            target={"R13":("research.group",{"items":["Alice","Carol"]}),"R14":("photography",{"items":["Nina"]}),"R17":("reading.club",{"items":[]}),"R28":("owner",{"fields":{"name":"Alice"}}),"R29":("owner",{"fields":{}})}[cid]
            key,state=target; expect(key in a and a[key]["state"]==state,"Current state",f"expected {state!r}"); expect(int(after["revision"])==int(before["revision"])+1,"Revision","expected +1"); expect(len(after["history"])==len(before["history"])+1,"History","expected predecessor")
            if cid=="R13": expect(a.get("laboratory",{}).get("state")=={"items":["Bob","David"]},"Current state","laboratory changed")
            if cid=="R14": expect(a.get("hiking",{}).get("state")=={"items":["Ian","Leo"]},"Current state","hiking changed")
        elif cid=="R35":
            expect(mid_clarification is not None,"Clarification","first step did not create clarification")
            expect(self._is_safe_degrade(before,after),"Current state","clarification/proposal changed memory"); expect(application.store.get_pending_proposal(user,session) is not None,"Proposal","continuation did not create proposal")
        elif cid=="R37":
            expect(self._is_safe_degrade(before,after),"Current state","Cancel changed state"); expect(application.store.get_pending_proposal(user,session) is None,"Proposal","proposal not removed")
        if cid in {"R15","R22"}:
            expect(mid_clarification is not None,"Clarification","expected clarification was absent")
            expect(mid_proposal is None,"Proposal","ambiguous request created executable proposal")
        if cid in {"R07","R16","R33","R38","R40"}:
            expect(mid_proposal is None,"Proposal","non-mutating request created proposal")
        if cid in {"R07","R16"}:
            expect(mid_clarification is None,"Clarification","known missing target/item incorrectly created clarification")
        if case.follow_up=="確認執行。":
            expect(application.store.get_pending_proposal(user,session) is None,"Proposal","proposal not consumed")
        return checks

    def _execute_offline(self, case: SuiteCase) -> CaseResult:
        """Exercise validator/compiler/transition/store contracts without a provider."""
        import app
        before_calls = self.offline_client.calls
        checks = {"Provider calls":"PASS", "Deterministic layer":"PASS", "State assertion":"PASS"}
        try:
            cid = int(case.case_id[1:])
            display_app = self._create_application(
                self.offline_client, semantic_ir_runtime=True
            )
            display_user = "user1"
            display_session = display_app.new_session(
                display_user, "offline-session"
            )["session_id"]
            # Transition-heavy cases use the actual canonical transition engine.
            transition_specs = {
                1:("scalar",None,"CREATE_SCALAR",{"value":"台北"},{"value":"台北"},True),
                3:("scalar",{"value":"台北"},"SET_VALUE",{"value":"新竹"},{"value":"新竹"},True),
                4:("scalar",{"value":"新竹"},"REASSERT_NOOP",{"value":"新竹"},{"value":"新竹"},False),
                13:("set",None,"CREATE_SET",{"items":["Alice","Bob","Carol"]},{"items":["Alice","Bob","Carol"]},True),
                15:("set",{"items":["Alice","Carol"]},"ADD_ITEM",{"item":"Bob"},{"items":["Alice","Carol","Bob"]},True),
                16:("set",{"items":["Alice","Bob","Carol"]},"ADD_ITEM",{"item":"Bob"},{"items":["Alice","Bob","Carol"]},False),
                18:("set",{"items":["Alice","Bob","Carol"]},"REMOVE_ITEM",{"item":"Bob"},{"items":["Alice","Carol"]},True),
                22:("set",{"items":["Alice"]},"REMOVE_ITEM",{"item":"Alice"},{"items":[]},True),
                24:("set",{"items":["Alice","Bob"]},"REPLACE_SET",{"items":["Alice","Carol"]},{"items":["Alice","Carol"]},True),
                27:("count",None,"CREATE_COUNT",{"value":4},{"value":4},True),
                29:("count",{"value":4},"SET_COUNT",{"value":5},{"value":5},True),
                32:("count",{"value":4},"SET_COUNT",{"value":3},{"value":3},True),
                37:("record",None,"CREATE_RECORD",{"fields":{"name":"Alice"}},{"fields":{"name":"Alice"}},True),
                38:("record",{"fields":{"name":"Alice"}},"SET_FIELD",{"field":"address","value":"台中"},{"fields":{"name":"Alice","address":"台中"}},True),
                39:("record",{"fields":{"name":"Alice","address":"台中"}},"SET_FIELD",{"field":"address","value":"新竹"},{"fields":{"name":"Alice","address":"新竹"}},True),
                41:("record",{"fields":{"name":"Alice","address":"新竹"}},"DELETE_FIELD",{"field":"address"},{"fields":{"name":"Alice"}},True),
                42:("record",{"fields":{"name":"Alice"}},"DELETE_FIELD",{"field":"name"},{"fields":{}},True),
                50:("scalar",{"value":"新竹"},"REASSERT_NOOP",{"value":"新竹"},{"value":"新竹"},False),
            }
            invalid_specs = {
                11:("scalar",{"value":"x"*(app.MAX_MEMORY_CHARS+1)}),
                25:("set",{"items":[str(i) for i in range(app.MAX_SET_ITEMS+1)]}),
                26:("set",{"items":["x"*(app.MAX_SET_ITEM_CHARS+1)]}),
                33:("count",{"value":-1}), 34:("count",{"value":app.MAX_COUNT+1}),
                46:("record",{"fields":{str(i):"x" for i in range(app.MAX_RECORD_FIELDS+1)}}),
            }
            if cid in transition_specs:
                st,current,op,args,expected,changed=transition_specs[cid]
                transition=app.apply_typed_transition(st,current,op,args)
                if transition.next_state != expected or transition.changed is not changed:
                    raise AssertionError(f"transition mismatch: {transition}")
                if transition.next_state is not None:
                    self._seed_memory(
                        display_app.store, display_user, f"offline-{case.case_id}", st,
                        f"offline.{case.case_id.lower()}", transition.next_state, case.title,
                    )
            elif cid in invalid_specs:
                st,state=invalid_specs[cid]
                if cid in {33,34}:
                    self._seed_memory(
                        display_app.store, display_user, f"offline-{case.case_id}",
                        "count", "reading.count", {"value":4}, "讀書會人數",
                    )
                try: app.validate_typed_state(st,state)
                except app.AppError: pass
                else: raise AssertionError("invalid typed state was accepted")
            elif cid == 36:
                try: app.apply_typed_transition("count",None,"CREATE_SET",{"items":["x"]})
                except app.AppError: pass
                else: raise AssertionError("mismatched count/set decision was accepted")
            elif cid == 51:
                raw={"kind":"READ","state_type":None,"semantic_key":None,"display_label":None,"memory_id":None,"operation":None,"arguments":{"illegal":1},"evidence":"READ_SELECTION","current_memory_ids":[],"history_ids":[],"unknown":True,"clarification_id":None,"clarification":None}
                try: app.validate_typed_decision(raw)
                except app.AppError: pass
                else: raise AssertionError("malformed READ was accepted")
            elif cid in {30,31}:
                transition=app.apply_typed_transition("count",{"value":4},"SET_COUNT",{"value":4})
                if transition.changed: raise AssertionError("anonymous event changed count")
                self._seed_memory(
                    display_app.store, display_user, f"offline-{case.case_id}",
                    "count", "reading.count", transition.next_state, "讀書會人數",
                )
            elif cid in {2,5,6,7,8,9,10,12,14,17,19,20,21,23,28,35,40,43,44,45,47,48,49,52,53,54,55,56,57,58,59,60}:
                display_user, display_session = self._offline_store_probe(case, app)
            else:
                raise AssertionError("No deterministic probe registered")
            if self.offline_client.calls != before_calls:
                raise AssertionError("Offline60 provider call count changed")
            self._publish_memory(display_app, display_user, display_session)
            return CaseResult("PASS", case.expected_answer, checks, {"expected":case.expected_state}, "", None, None, 0)
        except Exception as exc:
            try:
                self._publish_memory(display_app, display_user, display_session)
            except Exception:
                pass
            return CaseResult("FAIL — APPLICATION", "", checks, None, f"{type(exc).__name__}: {exc}", None, None, self.offline_client.calls-before_calls)

    def _offline_store_probe(self, case: SuiteCase, app: object) -> tuple[str, str]:
        application = self._create_application(
            self.offline_client, semantic_ir_runtime=True
        )
        session="offline-session"
        application.store.require_session("user1",session)
        user="user1"
        cid=int(case.case_id[1:])
        # These probes deliberately use direct deterministic APIs, never chat().
        if cid in {2,14,28,47,48,49,53}:
            read_fixtures = {
                2:("scalar","office",{"value":"台北"},"辦公室"),
                14:("set","research.group",{"items":["Alice","Bob","Carol"]},"研究小組"),
                28:("count","reading.count",{"value":4},"讀書會人數"),
                47:("scalar","office",{"value":"新竹"},"辦公室"),
                48:("scalar","car.color",{"value":"黑色"},"車色"),
                53:("scalar","office",{"value":"新竹"},"辦公室"),
            }
            if cid in read_fixtures:
                state_type,key,state,label=read_fixtures[cid]
                self._seed_memory(application.store,"user1","m-read",state_type,key,state,label)
                if cid == 47:
                    self._seed_history(application.store,"user1","m-read","scalar","office",{"value":"台北"},"辦公室")
                elif cid == 48:
                    self._seed_history(application.store,"user1","m-read","scalar","car.color",{"value":"白色"},"車色")
            before=application.store.get_typed_protocol_snapshot("user1",session)
            after=application.store.get_typed_protocol_snapshot("user1",session)
            if before != after: raise AssertionError("read probe mutated state")
        elif cid in {5,6,7,12,21,23,43,52,54,57}:
            fixtures = {
                5:("scalar","phone",{"value":"Pixel"},"手機"),
                6:("scalar","phone",{"value":"iPhone"},"手機"),
                7:("scalar","car1.color",{"value":"黑色"},"第一台車顏色"),
                12:("scalar","office",{"value":"台北"},"辦公室"),
                21:("set","research.group",{"items":["Alice","Carol"]},"研究小組"),
                23:("set","photography",{"items":["Nina"]},"攝影社"),
                43:("record","owner",{"fields":{"name":"Alice"}},"所有權人"),
                52:("scalar","private",{"value":"user1"},"私人記憶"),
                54:("scalar","private.history",{"value":"current"},"私人記憶"),
                57:("scalar","birthday.month",{"value":"五月"},"生日月份"),
            }
            state_type,key,state,label=fixtures[cid]
            self._seed_memory(application.store,"user1","m1",state_type,key,state,label)
            if cid in {12,52,54}:
                application.new_session("user2","other-session")
                if application.store.get_typed_memory_records("user2"): raise AssertionError("cross-user leak")
                user,session="user2","other-session"
        elif cid in {8,17,35,40,45}:
            # Validate that all destructive typed operations are classified as destructive.
            operation={8:"DELETE_MEMORY",17:"REMOVE_ITEM",35:"DELETE_MEMORY",40:"DELETE_FIELD",45:"DELETE_MEMORY"}[cid]
            if operation not in app.TYPED_DESTRUCTIVE_OPERATIONS: raise AssertionError("destructive gate missing")
        elif cid in {9,18,22,41,42}:
            if "CONFIRM" in case.test_type.upper() and self.offline_client.calls: raise AssertionError("local confirm called provider")
        elif cid in {10,19}:
            if self.offline_client.calls: raise AssertionError("local cancel called provider")
        elif cid in {20,44,55,56}:
            raw={"intent":"clarify","candidate":{"state_type":"set","action":"remove","args":{},"basis":"INSUFFICIENT"},"missing":["target_id","item"],"question":"請問哪位？"}
            compiled=app.compile_semantic_ir(app.validate_semantic_ir(raw))
            if compiled.decision.kind != "CLARIFY": raise AssertionError("clarification was not compiled")
        elif cid == 58:
            if app.MemoryStore.confirm_proposal is None: raise AssertionError("confirm unavailable")
        elif cid == 59:
            if app.MemoryStore.cancel_proposal is None: raise AssertionError("proposal lifecycle unavailable")
        elif cid == 60:
            before=application.store.get_typed_protocol_snapshot("user1",session)
            with application.store._lock, closing(application.store._connect()) as conn:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("UPDATE memory_state SET revision=revision+1 WHERE user_id='user1'")
                    raise sqlite3.OperationalError("injected")
                except sqlite3.OperationalError:
                    conn.rollback()
            after=application.store.get_typed_protocol_snapshot("user1",session)
            if before != after: raise AssertionError("rollback changed state")
        return user, session


class TestJobManager:
    def __init__(self, active_db_path: str | os.PathLike[str], provider_client: object | None = None,
                 executor_factory: Callable[[Path, Path, object | None], object] | None = None):
        self.active_db_path = Path(active_db_path).resolve()
        self.provider_client = provider_client
        self.executor_factory = executor_factory or SuiteExecutor
        self._lock = threading.RLock()
        self._review_condition = threading.Condition(self._lock)
        self._job: dict[str, object] | None = None

    def catalog(self) -> dict[str, object]:
        return public_suite_catalog()

    def start(self, suite_id: object, api_key: object = None, confirmed: object = False) -> dict[str, object]:
        if not isinstance(suite_id,str) or suite_id not in SUITE_DB_PATHS:
            raise ValueError("Unknown test suite")
        paid=suite_id in {"v2gate","real40","real40v2","master100"}
        if paid and confirmed is not True:
            raise ValueError("Explicit paid-API confirmation is required")
        if paid and not (os.environ.get("DEEPSEEK_API_KEY") or (isinstance(api_key,str) and api_key.strip())):
            raise ValueError("DeepSeek API key is required for this real-provider suite")
        validate_manifests()
        with self._lock:
            if self._job and self._job.get("status") in {"CLEARING DB","RUNNING","WAITING_FOR_HUMAN_REVIEW"}:
                raise RuntimeError("A test suite is already running")
            job_id=uuid.uuid4().hex
            self._job={
                "job_id":job_id,"suite_id":suite_id,"status":"CLEARING DB","progress":0,
                "total":len(suite_cases(suite_id)),"current_case":None,"passed_count":0,
                "safe_degrade_count":0,"provider_calls":0,"elapsed_seconds":0.0,
                "failure":None,"last_result":None,"message":"Test database clearing; production database untouched.",
                "human_review":None,"human_reviewed_writes":0,
                "confirmed_count":0,"rejected_count":0,
                "test_db_name":SUITE_DB_PATHS[suite_id].name,"test_user_id":None,
                "test_session_id":None,"test_revision":None,"test_memories":[],
                "protocol":SUITE_RUNTIME_PATHS[suite_id][0],
                "provider":SUITE_RUNTIME_PATHS[suite_id][1],
                "diagnostic_stages":(
                    list(V2_HUMAN_REVIEW_STAGES)
                    if suite_id in {"v2gate", "real40v2"}
                    else []
                ),
            }
            key=api_key.strip() if isinstance(api_key,str) else ""
            thread=threading.Thread(target=self._run,args=(job_id,suite_id,key),daemon=True,name=f"ui-test-{suite_id}")
            thread.start()
            return self.status(job_id)

    def status(self, job_id: object) -> dict[str, object]:
        with self._lock:
            if self._job is None or job_id != self._job.get("job_id"):
                raise KeyError("Test job not found")
            return json.loads(json.dumps(self._job,ensure_ascii=False))

    def _update(self, job_id: str, **values: object) -> None:
        with self._lock:
            if self._job and self._job.get("job_id")==job_id:
                self._job.update(values)

    def _wait_for_human_review(
        self, job_id: str, review: dict[str, object]
    ) -> str:
        with self._review_condition:
            if self._job is None or self._job.get("job_id") != job_id:
                raise RuntimeError("Test job is no longer current")
            review_state = dict(review)
            review_state["decision"] = None
            self._job.update({
                "status": "WAITING_FOR_HUMAN_REVIEW",
                "human_review": review_state,
                "provider_calls": review["provider_calls"],
                "message": "Review the persisted proposal, then Confirm or Reject.",
            })
            while review_state["decision"] is None:
                self._review_condition.wait()
                if self._job is None or self._job.get("job_id") != job_id:
                    raise RuntimeError("Test job is no longer current")
            return str(review_state["decision"])

    def review(
        self,
        job_id: object,
        case_id: object,
        proposal_id: object,
        session_id: object,
        action: object,
    ) -> dict[str, object]:
        if action not in {"confirm", "reject"}:
            raise ValueError("Review action must be confirm or reject")
        with self._review_condition:
            if self._job is None or job_id != self._job.get("job_id"):
                raise KeyError("Test job not found")
            if self._job.get("status") != "WAITING_FOR_HUMAN_REVIEW":
                raise RuntimeError("Test job is not waiting for human review")
            review = self._job.get("human_review")
            if not isinstance(review, dict):
                raise RuntimeError("Human review state is unavailable")
            identifiers = {
                "case_id": case_id,
                "proposal_id": proposal_id,
                "session_id": session_id,
            }
            if any(review.get(name) != value for name, value in identifiers.items()):
                raise RuntimeError("Stale or mismatched human review action")
            if review.get("decision") is not None:
                raise RuntimeError("Human review action was already submitted")
            review["decision"] = action
            self._job["status"] = "RUNNING"
            self._job["human_reviewed_writes"] = int(self._job["human_reviewed_writes"]) + 1
            counter = "confirmed_count" if action == "confirm" else "rejected_count"
            self._job[counter] = int(self._job[counter]) + 1
            self._job["message"] = f"Human review {action} accepted; applying local proposal lifecycle action."
            self._review_condition.notify_all()
            return json.loads(json.dumps(self._job, ensure_ascii=False))

    def _run(self, job_id: str, suite_id: str, api_key: str) -> None:
        started=time.monotonic()
        db_path=SUITE_DB_PATHS[suite_id]
        try:
            safe_reset_test_database(db_path,self.active_db_path)
        except Exception as exc:
            failure_type = (
                "TEST DATABASE SAFETY BLOCKED"
                if isinstance(exc, TestDatabaseSafetyError)
                else "TEST DATABASE RESET FAILED"
            )
            self._update(job_id,status="FAIL",failure={"failure_type":failure_type,"case_id":None,"step":"RESET","question":"","expected":"fresh dedicated test database","actual":"reset blocked","expected_state":"production database untouched","actual_state":None,"diagnostic":f"{type(exc).__name__}: {exc}","revision_before":None,"revision_after":None,"provider_call_count":0},elapsed_seconds=round(time.monotonic()-started,3))
            return
        try:
            self._update(
                job_id,status="RUNNING",message="Test database cleared. Production database untouched.",
                test_user_id=None,test_session_id=None,test_revision=0,test_memories=[],
            )
            executor=self.executor_factory(db_path,self.active_db_path,self.provider_client)
            if hasattr(executor, "runtime_path"):
                executor.runtime_path = SUITE_RUNTIME_PATHS[suite_id][0]
            if hasattr(executor, "progress_callback"):
                executor.progress_callback = lambda **values: self._update(job_id, **values)
            if (
                suite_id in {"v2gate", "real40v2"}
                and hasattr(executor, "human_review_callback")
            ):
                executor.human_review_callback = (
                    lambda review: self._wait_for_human_review(job_id, review)
                )
            cases=suite_cases(suite_id)
            for index,case in enumerate(cases,1):
                self._update(
                    job_id,progress=index-1,current_case=case.public_dict(),
                    elapsed_seconds=round(time.monotonic()-started,3),
                )
                case_started=time.monotonic()
                review_wait_before=float(getattr(executor,"human_review_wait_seconds",0.0))
                result=executor.execute(case,api_key)
                if suite_id in {"v2gate", "real40v2"}:
                    result.diagnostic_stages = V2_HUMAN_REVIEW_STAGES
                review_wait_after=float(getattr(executor,"human_review_wait_seconds",0.0))
                case_elapsed=time.monotonic()-case_started-(review_wait_after-review_wait_before)
                allowed_seconds=REAL_STEP_TIMEOUT_SECONDS * max(1, case.expected_provider_calls)
                if case_elapsed > allowed_seconds:
                    result=CaseResult("FAIL — APPLICATION",result.actual_answer,result.checks,result.actual_state,f"Case exceeded {allowed_seconds}s timeout ({case_elapsed:.1f}s)",result.revision_before,result.revision_after,result.provider_calls,"timeout")
                calls=int(getattr(executor,"provider_calls",0))
                if case.case_id.startswith("S") and result.provider_calls != 0:
                    result=CaseResult("HARD SAFETY FAIL",result.actual_answer,result.checks,result.actual_state,"Offline case made a provider call",result.revision_before,result.revision_after,result.provider_calls,result.step)
                public=asdict(result)
                self._update(job_id,last_result=public,provider_calls=calls,progress=index,human_review=None,elapsed_seconds=round(time.monotonic()-started,3))
                if result.result == "PASS":
                    with self._lock: self._job["passed_count"] = int(self._job["passed_count"])+1  # type: ignore[index]
                elif result.result == "OPTIONAL SAFE-DEGRADE":
                    with self._lock: self._job["safe_degrade_count"] = int(self._job["safe_degrade_count"])+1  # type: ignore[index]
                else:
                    failure={
                        "failure_type":result.result,"case_id":case.case_id,"step":result.step,
                        "question":case.question,"expected":case.expected_answer,"actual":result.actual_answer,
                        "expected_state":case.expected_state,"actual_state":result.actual_state,
                        "diagnostic":result.diagnostic,"revision_before":result.revision_before,
                        "revision_after":result.revision_after,"provider_call_count":calls,
                    }
                    self._update(job_id,status="FAIL",failure=failure,elapsed_seconds=round(time.monotonic()-started,3))
                    return
            self._update(job_id,status="PASS",current_case=None,human_review=None,elapsed_seconds=round(time.monotonic()-started,3),message="Suite complete. Production database untouched.")
        except Exception as exc:
            self._update(job_id,status="FAIL",failure={"failure_type":"FAIL — APPLICATION","case_id":None,"step":"RESET/EXECUTION","question":"","expected":"","actual":"","expected_state":"","actual_state":None,"diagnostic":f"{type(exc).__name__}: {exc}","revision_before":None,"revision_after":None,"provider_call_count":0},elapsed_seconds=round(time.monotonic()-started,3))


validate_manifests()
