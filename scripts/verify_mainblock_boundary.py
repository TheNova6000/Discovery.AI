"""Enforces the main-block layout (owner request, 2026-10-28):

    backend/main_block/
      interface.py                 <- clients import ONLY this
      service.py api.py models.py store.py   the door
      reasoning_engine/  (Discovery.AI, own interface.py)
      research_engine/   (Dewey, own interface.py)
    backend/chat, backend/tunin    <- clients, outside the main block

Rules (static AST scan; relative imports are resolved):
  1. clients (backend/chat, backend/tunin) import from the main block only via
     `backend.main_block.interface`
  2. the door imports each engine only via that engine's `interface`
  3. the reasoning engine imports the research engine only via
     `research_engine.interface`, and never the door or clients
  4. the research engine never imports the reasoning engine, the door, or clients
Shared infrastructure anyone may use: backend.llm (transport), backend.paths,
backend.api.auth (route dependency). Fails on any violation.
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MB = "backend.main_block"
RE = f"{MB}.reasoning_engine"
DE = f"{MB}.research_engine"
DOOR_MODULES = (f"{MB}.service", f"{MB}.api", f"{MB}.models", f"{MB}.store", f"{MB}.interface")
CLIENTS = ("backend.chat", "backend.tunin")


def module_of(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    here = module_of(path)
    package = here if path.name == "__init__.py" else here.rsplit(".", 1)[0]
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            # "from pkg import name": name may be a submodule ("from backend.main_block
            # import interface"), so judge pkg.name; for plain names inside a module
            # the prefix checks give the same verdict either way.
            out += [f"{mod}.{a.name}" for a in node.names]
    return [m for m in out if m.startswith("backend.")]


def inside(mod: str, pkg: str) -> bool:
    return mod == pkg or mod.startswith(pkg + ".")


def check(src: str, target: str) -> str | None:
    if inside(src, CLIENTS[0]) or inside(src, CLIENTS[1]):
        if inside(target, MB) and not inside(target, f"{MB}.interface"):
            return "clients may import the main block only via backend.main_block.interface"
        return None
    if src in DOOR_MODULES or src == MB:
        if inside(target, RE) and not inside(target, f"{RE}.interface"):
            return "the door may import the reasoning engine only via reasoning_engine.interface"
        if inside(target, DE) and not inside(target, f"{DE}.interface"):
            return "the door may import the research engine only via research_engine.interface"
        return None
    if inside(src, RE):
        if inside(target, DE) and not inside(target, f"{DE}.interface"):
            return "the reasoning engine may import the research engine only via research_engine.interface"
        if any(inside(target, m) for m in DOOR_MODULES) or inside(target, CLIENTS[0]) or inside(target, CLIENTS[1]):
            return "the reasoning engine must not import the door or clients"
        return None
    if inside(src, DE):
        if inside(target, RE) or any(inside(target, m) for m in DOOR_MODULES) or \
                inside(target, CLIENTS[0]) or inside(target, CLIENTS[1]):
            return "the research engine must not import the reasoning engine, the door, or clients"
    return None


def main() -> int:
    problems = []
    for path in sorted((ROOT / "backend").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        src = module_of(path)
        for target in imports(path):
            why = check(src, target)
            if why:
                problems.append(f"{path.relative_to(ROOT).as_posix()} imports {target}: {why}")
    for p in problems:
        print("[FAIL]", p)
    print("\nBoundary holds." if not problems else f"\n{len(problems)} boundary problem(s).")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
