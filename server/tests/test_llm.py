"""Unit tests for multi-provider LLM integration (Claude Code & Antigravity agy)."""
import json
import subprocess
from unittest.mock import MagicMock

import pytest

from server import config, llm


def make_proc(stdout: str, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(args=["test"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_resolve_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
    assert llm.resolve_provider() == "claude"

    monkeypatch.setattr(config, "LLM_PROVIDER", "agy")
    assert llm.resolve_provider() == "agy"

    monkeypatch.setattr(config, "LLM_PROVIDER", "auto")
    monkeypatch.setenv("MANGA_AGY_CMD", json.dumps(["fake_agy"]))
    monkeypatch.delenv("MANGA_CLAUDE_CMD", raising=False)
    assert llm.resolve_provider() == "agy"

    monkeypatch.setenv("MANGA_CLAUDE_CMD", json.dumps(["fake_claude"]))
    assert llm.resolve_provider() == "claude"


def test_run_claude_success():
    fake_proc = MagicMock(return_value=make_proc(json.dumps({
        "result": "success",
        "total_cost_usd": 0.12,
        "num_turns": 4,
        "is_error": False,
    })))
    res = llm._run_claude("prompt", run_proc=fake_proc)
    assert res.text == "success"
    assert res.cost_usd == 0.12
    assert res.turns == 4


def test_run_claude_limit():
    fake_proc = MagicMock(return_value=make_proc(json.dumps({
        "result": "usage limit reached",
        "is_error": True,
    })))
    with pytest.raises(llm.LlmLimitError):
        llm._run_claude("prompt", run_proc=fake_proc)


def test_run_agy_success():
    fake_proc = MagicMock(return_value=make_proc(json.dumps({
        "conversation_id": "conv-123",
        "status": "SUCCESS",
        "response": "done agy",
        "duration_seconds": 2.5,
        "num_turns": 2,
        "usage": {"input_tokens": 20000, "output_tokens": 1000},
    })))
    res = llm._run_agy("prompt", run_proc=fake_proc)
    assert res.text == "done agy"
    assert res.cost_usd > 0
    assert res.turns == 2


def test_run_agy_limit():
    fake_proc = MagicMock(return_value=make_proc(json.dumps({
        "status": "ERROR",
        "response": "RESOURCE_EXHAUSTED: quota exceeded for model",
    })))
    with pytest.raises(llm.LlmLimitError):
        llm._run_agy("prompt", run_proc=fake_proc)


def test_run_agy_error():
    fake_proc = MagicMock(return_value=make_proc(json.dumps({
        "status": "ERROR",
        "response": "something failed",
    })))
    with pytest.raises(llm.LlmError):
        llm._run_agy("prompt", run_proc=fake_proc)


def test_run_agent_dispatch(monkeypatch):
    claude_called = []
    agy_called = []
    monkeypatch.setattr(llm, "_run_claude", lambda *a, **k: claude_called.append(1) or llm.LlmResult("c", 0.1, 1))
    monkeypatch.setattr(llm, "_run_agy", lambda *a, **k: agy_called.append(1) or llm.LlmResult("a", 0.05, 1))

    r1 = llm.run_agent("p", run_proc=MagicMock(), provider="claude")
    assert r1.text == "c"
    assert len(claude_called) == 1

    r2 = llm.run_agent("p", run_proc=MagicMock(), provider="agy")
    assert r2.text == "a"
    assert len(agy_called) == 1
