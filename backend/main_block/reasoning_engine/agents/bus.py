from __future__ import annotations

import asyncio
from typing import AsyncIterator, Union

from .messages import BoundaryHitMessage, ExpansionRequestMessage

AgentMessage = Union[BoundaryHitMessage, ExpansionRequestMessage]


class MessageBus:
    """A single asyncio.Queue shared by one Master and its entire Ground Agent tree
    for one run (docs/Phases.md Phase 4). Every Ground Agent, at any depth, only
    ever *sends* on this bus; only the Master consumes it — so even though the
    transport is one shared queue, the only communication path that is ever
    realized is Ground -> (ancestor) Master, never Ground -> Ground (Rules.md
    rule 9's "no lateral/peer messaging").
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[AgentMessage | None] = asyncio.Queue()

    async def send(self, message: AgentMessage) -> None:
        await self._queue.put(message)

    async def close(self) -> None:
        """Sentinel that ends `messages()`'s iteration once the run is done."""
        await self._queue.put(None)

    async def messages(self) -> AsyncIterator[AgentMessage]:
        while True:
            message = await self._queue.get()
            if message is None:
                break
            yield message
