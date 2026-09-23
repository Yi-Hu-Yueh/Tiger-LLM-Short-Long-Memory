from __future__ import annotations

import os

import pytest

from memory_real_gate import run_real_memory_gate


def test_real_llm_memory_extraction_gate_skips_without_configuration():
    if os.environ.get("RUN_REAL_LLM_TEST", "false").lower() != "true":
        pytest.skip("real LLM gate disabled")
    provider = os.environ.get("MEMORY_LLM_PROVIDER", "deepseek").lower()
    if provider == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY is required for DeepSeek real gate")

    report = run_real_memory_gate(
        case_limit=int(os.environ["REAL_LLM_CASE_LIMIT"])
        if os.environ.get("REAL_LLM_CASE_LIMIT")
        else None
    )
    assert report["phase_1c_pass"], report["failed_cases"]
