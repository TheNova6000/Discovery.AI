import sys

# Windows' default console codec (cp1252) can't encode arbitrary Unicode --
# and this project's print()-based diagnostics regularly echo raw LLM output
# (docs/Memory.md: a Gemini response containing a Unicode non-breaking hyphen,
# U+2011, crashed an entire investigation on Windows because one such print()
# wasn't wrapped in the same sanitization backend/questions/llm_client.py uses
# for its own provider-failure logging). Reconfiguring here, at the top of the
# package every submodule imports first, covers every print() -- including
# ones added later -- and any third-party library that prints/logs raw
# provider text directly to stdout/stderr, not just the call sites known
# today.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="backslashreplace")
