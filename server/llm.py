"""Run an LLM agent unattended (headless) and report what it cost.

Supports both:
  - Claude Code CLI (`claude`) via Anthropic
  - Antigravity CLI (`agy`) via Google Gemini

The agent may only Read and Write files. The server validates whatever it wrote and decides whether
to retry; the agent is never trusted to have produced valid output.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import config


class LlmError(RuntimeError):
    pass


class LlmLimitError(LlmError):
    """The plan's usage limit (or a rate limit) was hit. Trying again right away cannot work, so callers stop."""


LIMIT_RE = re.compile(
    r"usage limit|rate limit|limit reached|too many requests|quota|credit balance| 429 |RESOURCE_EXHAUSTED",
    re.I,
)
LIMIT_MESSAGE = (
    "LLM usage limit reached. Everything finished so far is kept: press Retry after your limit resets "
    "(check usage in Claude Code or Antigravity)."
)


@dataclass
class LlmResult:
    text: str
    cost_usd: float
    turns: int


def resolve_provider() -> str:
    """Resolve whether to run Claude Code ('claude') or Antigravity CLI ('agy')."""
    pref = config.LLM_PROVIDER
    if pref in {"claude", "agy"}:
        return pref

    # auto mode: check if explicit overrides exist first
    if os.environ.get("MANGA_AGY_CMD") and not os.environ.get("MANGA_CLAUDE_CMD"):
        return "agy"
    if os.environ.get("MANGA_CLAUDE_CMD"):
        return "claude"

    # probe which executable is available in PATH or common install directories
    has_claude = bool(shutil.which("claude") or Path(Path.home() / ".local" / "bin" / "claude.exe").exists())
    has_agy = bool(shutil.which("agy") or Path(Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe").exists())

    if has_claude:
        return "claude"
    if has_agy:
        return "agy"

    return "claude"


def claude_command() -> list[str]:
    """MANGA_CLAUDE_CMD (JSON list) lets tests and unusual installs override the executable."""
    override = os.environ.get("MANGA_CLAUDE_CMD")
    if override:
        return json.loads(override)
    found = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")
    if not Path(found).exists() and not shutil.which(found):
        raise LlmError("Claude Code CLI not found. Install it and log in, or set MANGA_CLAUDE_CMD (or switch to Antigravity agy).")
    return [found]


def agy_command() -> list[str]:
    """MANGA_AGY_CMD (JSON list) lets tests and unusual installs override the executable."""
    override = os.environ.get("MANGA_AGY_CMD")
    if override:
        return json.loads(override)
    found = shutil.which("agy") or str(Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe")
    if not Path(found).exists() and not shutil.which(found):
        raise LlmError("Antigravity CLI (agy) not found. Install it and log in, or set MANGA_AGY_CMD (or switch to Claude Code).")
    return [found]


def _run_claude(
    prompt: str,
    *,
    run_proc: Callable[..., subprocess.CompletedProcess],
    max_turns: int = 40,
    timeout: int = 900,
) -> LlmResult:
    cmd = claude_command() + [
        "-p", "--allowedTools", "Read", "Write", "--permission-mode", "dontAsk",
        "--output-format", "json", "--max-turns", str(max_turns), "--no-session-persistence",
    ]
    proc = run_proc(cmd, cwd=config.ROOT, input_text=prompt, timeout=timeout)
    if proc.returncode != 0:
        text = f"{proc.stderr or ''} {proc.stdout or ''}"
        if LIMIT_RE.search(text):
            raise LlmLimitError(LIMIT_MESSAGE)
        raise LlmError(f"Claude agent exited with {proc.returncode}: {(proc.stderr or proc.stdout)[-300:]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise LlmError(f"Claude agent output was not JSON: {proc.stdout[-200:]}")
    if data.get("is_error"):
        reason = str(data.get("result"))
        if LIMIT_RE.search(reason):
            raise LlmLimitError(LIMIT_MESSAGE)
        raise LlmError(f"Claude agent reported an error: {reason[:300]}")
    return LlmResult(
        text=str(data.get("result", "")),
        cost_usd=float(data.get("total_cost_usd") or 0),
        turns=int(data.get("num_turns") or 0),
    )


def _run_agy(
    prompt: str,
    *,
    run_proc: Callable[..., subprocess.CompletedProcess],
    max_turns: int = 40,
    timeout: int = 900,
) -> LlmResult:
    cmd = agy_command() + [
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "-p", "-",
    ]
    if config.AGY_MODEL:
        cmd.extend(["--model", config.AGY_MODEL])

    proc = run_proc(cmd, cwd=config.ROOT, input_text=prompt, timeout=timeout)
    if proc.returncode != 0:
        text = f"{proc.stderr or ''} {proc.stdout or ''}"
        if LIMIT_RE.search(text):
            raise LlmLimitError(LIMIT_MESSAGE)
        raise LlmError(f"Antigravity agy agent exited with {proc.returncode}: {(proc.stderr or proc.stdout)[-300:]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise LlmError(f"Antigravity agy output was not JSON: {proc.stdout[-200:]}")

    status = data.get("status")
    if status and status != "SUCCESS":
        reason = str(data.get("response") or data.get("error") or status)
        if LIMIT_RE.search(reason):
            raise LlmLimitError(LIMIT_MESSAGE)
        raise LlmError(f"Antigravity agy reported an error ({status}): {reason[:300]}")

    # Estimate cost from usage tokens if present
    usage = data.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    # Gemini 2.5 Flash pricing benchmark: ~$0.075 / 1M input, ~$0.30 / 1M output
    cost_usd = (input_tokens * 0.000000075) + (output_tokens * 0.0000003)

    return LlmResult(
        text=str(data.get("response", "")),
        cost_usd=round(cost_usd, 6),
        turns=int(data.get("num_turns") or 1),
    )


def run_agent(
    prompt: str,
    *,
    run_proc: Callable[..., subprocess.CompletedProcess],
    max_turns: int = 40,
    timeout: int = 900,
    provider: Optional[str] = None,
) -> LlmResult:
    """`run_proc` is the worker's cancellable subprocess runner (so Cancel can kill the agent)."""
    p = (provider or resolve_provider()).lower()
    if p == "agy":
        return _run_agy(prompt, run_proc=run_proc, max_turns=max_turns, timeout=timeout)
    return _run_claude(prompt, run_proc=run_proc, max_turns=max_turns, timeout=timeout)
