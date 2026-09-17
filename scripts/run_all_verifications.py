"""Verification-hygiene tooling (2026-09-17) -- runs every scripts/verify_*.py
and produces one machine-readable summary, categorizing each script into
exactly one bucket rather than a flat pass/fail:

  passed             -- exited 0
  environment_blocked -- exited non-zero, and its own output names a missing
                         LLM provider key as the reason (a real, pre-existing
                         environment gap in whatever machine runs this, not a
                         code defect)
  failed             -- exited non-zero for any other reason -- a real
                         regression or a genuine defect, never silently
                         folded into "environment_blocked"

This script does not replace reading any individual script's own output --
it exists so "did everything pass" has one honest, mechanically-produced
answer instead of an eyeballed scan of 40+ separate terminal runs.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_ENV_BLOCKED_MARKER = "No LLM provider key found in .env"


def _run_one(script: pathlib.Path) -> dict:
    started = time.time()
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    duration_s = round(time.time() - started, 1)
    output = result.stdout + result.stderr

    if result.returncode == 0:
        category = "passed"
    elif _ENV_BLOCKED_MARKER in output:
        category = "environment_blocked"
    else:
        category = "failed"

    return {
        "script": script.name,
        "category": category,
        "exit_code": result.returncode,
        "duration_s": duration_s,
    }


def run() -> dict:
    scripts = sorted(_SCRIPTS_DIR.glob("verify_*.py"))
    results = [_run_one(s) for s in scripts]

    summary = {
        "total_scripts": len(results),
        "passed": sum(1 for r in results if r["category"] == "passed"),
        "environment_blocked": sum(1 for r in results if r["category"] == "environment_blocked"),
        "failed": sum(1 for r in results if r["category"] == "failed"),
        "results": results,
    }
    return summary


if __name__ == "__main__":
    summary = run()
    print(json.dumps(summary, indent=2))
    print(
        f"\n{summary['passed']} passed, "
        f"{summary['environment_blocked']} environment-blocked, "
        f"{summary['failed']} failed, "
        f"out of {summary['total_scripts']} scripts.",
        file=sys.stderr,
    )
    sys.exit(1 if summary["failed"] > 0 else 0)
