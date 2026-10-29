"""Live, un-mocked end-to-end conversation for HUMAN review: a learner talks to
the Tuni'n chat model, asks a subject question mid-discovery (answered through
the main block), confirms the brief, a real main-block research job runs, and
the chat presents its grounded findings. Prints every turn.

Usage: python scripts/evaluate_chat_live.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.chat.engine import chat_turn, start_session  # noqa: E402

SCRIPT = [
    "I want to learn photosynthesis so I can teach it to my high school class",
    "How do the light-dependent reactions work?",
    "I know basic biology and chemistry",
    "about 4 hours a week for 6 weeks",
    "not sure, you decide",
    "not sure, you decide",
    "not sure, you decide",
    "not sure, you decide",
    "not sure, you decide",
]


async def main() -> None:
    started = time.time()
    session = await start_session("live-eval")
    print(f"TUNI'N: {session.messages[0].text}\n")
    for text in SCRIPT:
        if session.phase != "discovery":
            break
        reply = await chat_turn(session, text)
        session = reply.session
        print(f"LEARNER: {text}\nTUNI'N [{reply.reply.kind}, grounded={reply.reply.grounded}, phase={session.phase}]:\n{reply.reply.text}\n")
    if session.phase == "confirming":
        reply = await chat_turn(session, "yes, start the research")
        session = reply.session
        print(f"LEARNER: yes, start the research\nTUNI'N [{reply.reply.kind}, phase={session.phase}]:\n{reply.reply.text}\n")
        while session.phase == "researching" and time.time() - started < 1500:
            await asyncio.sleep(20)
            reply = await chat_turn(session, "status")
            session = reply.session
            print(f"[{time.time() - started:.0f}s] status -> phase={session.phase}: {reply.reply.text[:120]}")
        print(f"\nFINAL TUNI'N [{reply.reply.kind}, grounded={reply.reply.grounded}]:\n{reply.reply.text}")
    print(f"\n[total {time.time() - started:.0f}s]")


if __name__ == "__main__":
    asyncio.run(main())
