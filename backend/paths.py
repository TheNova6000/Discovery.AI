"""Repository root, defined once. Modules used to count folder levels up from
their own file ("parent.parent.parent"), which silently pointed at the wrong
place when the main block was restructured into deeper packages."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
