"""Run a Claude Code agent unattended (headless) and report what it cost.

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
from typing import Callable

from . import config


class LlmError(RuntimeError):
    pass


class LlmLimitError(LlmError):
    """The plan's usage limit (or a rate limit) was hit. Trying again right away cannot work, so callers stop."""


LIMIT_RE = re.compile(r"usage limit|rate limit|limit reached|too many requests|quota|credit balance|429", re.I)
LIMIT_MESSAGE = ("Claude usage limit reached. Everything finished so far is kept: press Retry after your limit resets "
                 "(check /usage in Claude Code).")


@dataclass
class LlmResult:
    text: str
    cost_usd: float
    turns: int


def claude_command() -> list[str]:
    """MANGA_CLAUDE_CMD (JSON list) lets tests and unusual installs override the executable."""
    override = os.environ.get("MANGA_CLAUDE_CMD")
    if override:
        return json.loads(override)
    found = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")
    if not Path(found).exists():
        raise LlmError("Claude Code CLI not found. Install it and log in, or set MANGA_CLAUDE_CMD.")
    return [found]


def run_agent(
    prompt: str,
    *,
    run_proc: Callable[..., subprocess.CompletedProcess],
    max_turns: int = 40,
    timeout: int = 900,
) -> LlmResult:
    """`run_proc` is the worker's cancellable subprocess runner (so Cancel can kill the agent)."""
    cmd = claude_command() + [
        "-p", "--allowedTools", "Read", "Write", "--permission-mode", "dontAsk",
        "--output-format", "json", "--max-turns", str(max_turns), "--no-session-persistence",
    ]
    proc = run_proc(cmd, cwd=config.ROOT, input_text=prompt, timeout=timeout)
    if proc.returncode != 0:
        text = f"{proc.stderr or ''} {proc.stdout or ''}"
        if LIMIT_RE.search(text):
            raise LlmLimitError(LIMIT_MESSAGE)
        raise LlmError(f"agent exited with {proc.returncode}: {(proc.stderr or proc.stdout)[-300:]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise LlmError(f"agent output was not JSON: {proc.stdout[-200:]}")
    if data.get("is_error"):
        reason = str(data.get("result"))
        if LIMIT_RE.search(reason):
            raise LlmLimitError(LIMIT_MESSAGE)
        raise LlmError(f"agent reported an error: {reason[:300]}")
    return LlmResult(text=str(data.get("result", "")), cost_usd=float(data.get("total_cost_usd") or 0), turns=int(data.get("num_turns") or 0))
