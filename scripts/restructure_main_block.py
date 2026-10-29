"""One-off restructure (2026-10-28, owner request): put Discovery.AI (reasoning
engine) + Dewey (research engine) + the door into one `backend/main_block/`
package, with everything that uses it outside. Moves with `git mv` (history
kept), rewrites every import, deletes the old paths (no compatibility shims).

Run from the repo root:  python scripts/restructure_main_block.py [--dry-run]
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DRY = "--dry-run" in sys.argv
RE = "backend/main_block/reasoning_engine"
DE = "backend/main_block/research_engine"

MOVES = [  # (old, new) -- directories unless noted
    ("backend/mainblock", "backend/main_block"),
    ("backend/agents", f"{RE}/agents"),
    ("backend/questions", f"{RE}/llm_steps"),
    ("backend/reasoning", f"{RE}/domain"),
    ("backend/research_api", f"{RE}/research_api"),
    ("backend/research", f"{RE}/research"),
    ("backend/graph", f"{RE}/graph"),
    ("backend/runtime", f"{RE}/runtime"),
    ("backend/roadmap", f"{RE}/roadmap"),
    ("backend/evidence", f"{RE}/evidence"),
    ("backend/dewey", DE),
]
SECOND_MOVES = [  # after the directory moves
    (f"{RE}/evidence/retrievers", f"{DE}/sources"),
    (f"{RE}/evidence/config.py", f"{DE}/config.py"),
    (f"{RE}/llm_steps/llm_client.py", "backend/llm/client.py"),
    (f"{RE}/llm_steps/llm_config.py", "backend/llm/config.py"),
]

# Longest prefixes first.
MODULE_MAP = [
    ("backend.evidence.retrievers", "backend.main_block.research_engine.sources"),
    ("backend.evidence.config", "backend.main_block.research_engine.config"),
    ("backend.evidence", "backend.main_block.reasoning_engine.evidence"),
    ("backend.questions.llm_client", "backend.llm.client"),
    ("backend.questions.llm_config", "backend.llm.config"),
    ("backend.questions", "backend.main_block.reasoning_engine.llm_steps"),
    ("backend.agents", "backend.main_block.reasoning_engine.agents"),
    ("backend.research_api", "backend.main_block.reasoning_engine.research_api"),
    ("backend.research", "backend.main_block.reasoning_engine.research"),
    ("backend.reasoning", "backend.main_block.reasoning_engine.domain"),
    ("backend.graph", "backend.main_block.reasoning_engine.graph"),
    ("backend.runtime", "backend.main_block.reasoning_engine.runtime"),
    ("backend.roadmap", "backend.main_block.reasoning_engine.roadmap"),
    ("backend.dewey", "backend.main_block.research_engine"),
    ("backend.mainblock", "backend.main_block"),
]
PATH_MAP = [(a.replace(".", "/"), b.replace(".", "/")) for a, b in MODULE_MAP]
CHAINS = "backend.main_block.reasoning_engine.model_chains"
CHAIN_NAMES = {"GROUND_MODEL_CHAIN", "MASTER_MODEL_CHAIN"}


def git(*args: str) -> None:
    print("git", *args)
    if not DRY:
        subprocess.run(["git", *args], cwd=ROOT, check=True)


def move(old: str, new: str) -> None:
    if not (ROOT / old).exists():
        print(f"skip (missing) {old}")
        return
    (ROOT / new).parent.mkdir(parents=True, exist_ok=True)
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", old], cwd=ROOT, capture_output=True).returncode == 0
    if tracked:
        git("mv", old, new)  # keeps history; untracked files inside a tracked dir move with it
    else:
        print(f"mv (untracked) {old} -> {new}")
        if not DRY:
            import shutil

            shutil.move(str(ROOT / old), str(ROOT / new))


def rewrite_text(text: str, path: pathlib.Path) -> str:
    for old, new in MODULE_MAP:
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    for old, new in PATH_MAP:
        text = re.sub(rf"(?<![\w/]){re.escape(old)}(?=[/\s.`'\")]|$)", new, text)
    rel = path.relative_to(ROOT).as_posix()
    # Relative imports that pointed at the moved LLM transport.
    if rel.startswith(f"{RE}/llm_steps/"):
        text = re.sub(r"^from \.llm_client import", "from backend.llm.client import", text, flags=re.M)
        text = re.sub(r"^from \.llm_config import", "from backend.llm.config import", text, flags=re.M)
    if rel == "backend/llm/client.py":
        text = re.sub(r"^from \.llm_config import", "from .config import", text, flags=re.M)
    # Retrievers now live under research_engine/sources; RetrievedResource under research_engine/resource.
    if rel.startswith(f"{DE}/sources/"):
        text = re.sub(r"^from \.\.models import RetrievedResource", "from ..resource import RetrievedResource", text, flags=re.M)
    # Model chains are reasoning-engine settings, not shared transport.
    def split_chain_import(match: re.Match) -> str:
        indent, module, names = match.group(1), match.group(2), [n.strip() for n in match.group(3).split(",")]
        chains = [n for n in names if n in CHAIN_NAMES]
        rest = [n for n in names if n not in CHAIN_NAMES]
        lines = []
        if rest:
            lines.append(f"{indent}from {module} import {', '.join(rest)}")
        if chains:
            lines.append(f"{indent}from {CHAINS} import {', '.join(chains)}")
        return "\n".join(lines)

    text = re.sub(r"^(\s*)from (backend\.llm\.config) import ([A-Za-z_, ]+)$", split_chain_import, text, flags=re.M)
    return text


def main() -> int:
    for old, new in MOVES:
        move(old, new)
    for old, new in SECOND_MOVES:
        move(old, new)
    if DRY:
        return 0
    files = [p for p in (ROOT / "backend").rglob("*.py") if "__pycache__" not in p.parts]
    files += [p for p in (ROOT / "scripts").rglob("*.py") if p.name != "restructure_main_block.py"]
    changed = 0
    for path in files:
        before = path.read_text(encoding="utf-8")
        after = rewrite_text(before, path)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed += 1
    print(f"rewrote imports in {changed} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
