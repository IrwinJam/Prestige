"""Checks that nothing which shouldn't be public is about to be committed.

This repo is public. It must never hold attack text, run logs, traces or keys. These tests look at every
file git would commit: tracked files plus untracked ones that aren't ignored.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 512 * 1024
BANNED_SUFFIXES = {".sqlite", ".sqlite3", ".jsonl", ".db"}
# Fields found in AgentDojo's per-task logs. A committed JSON file with several of them is run data.
LOG_FIELDS = {"suite_name", "pipeline_name", "user_task_id", "injection_task_id", "attack_type", "injections", "messages", "utility", "security"}


@pytest.fixture(scope="module")
def files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-c", "safe.directory=*", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [f for f in out.decode("utf-8").split("\0") if f]


def test_ignore_rules_cover_run_data():
    rules = {line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert {"runs/", ".env", "*.sqlite", "*.jsonl"} <= rules


def test_no_run_data_or_keys(files):
    bad = [f for f in files if f.startswith("runs/") or Path(f).name == ".env" or Path(f).suffix in BANNED_SUFFIXES]
    assert not bad, f"run data or keys would be committed: {bad}"


def test_no_large_files(files):
    big = [f for f in files if (ROOT / f).is_file() and (ROOT / f).stat().st_size > MAX_BYTES]
    assert not big, f"files over {MAX_BYTES // 1024} KB would be committed, which usually means raw logs: {big}"


def test_no_benchmark_logs(files):
    logs = []
    for f in files:
        path = ROOT / f
        if path.suffix != ".json" or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        first = data[0] if isinstance(data, list) and data else data
        if isinstance(first, dict) and len(LOG_FIELDS & first.keys()) >= 3:
            logs.append(f)
    assert not logs, f"benchmark logs would be committed: {logs}"
