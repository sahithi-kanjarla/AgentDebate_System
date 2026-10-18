import asyncio
from collections.abc import AsyncIterator

from app.schemas import DebateEvent


class DebateChannel:
    """Append-only event list for one running debate, with any number of followers.

    A subscriber starts at a position in the list, so a client connecting mid-debate first
    receives everything already emitted and then waits for the rest: nothing is missed and
    nothing is delivered twice.
    """

    def __init__(self) -> None:
        self.events: list[DebateEvent] = []
        self.finished = False
        self._cond = asyncio.Condition()

    @property
    def next_seq(self) -> int:
        return len(self.events)

    async def publish(self, event: DebateEvent) -> None:
        async with self._cond:
            self.events.append(event)
            self._cond.notify_all()

    async def finish(self) -> None:
        async with self._cond:
            self.finished = True
            self._cond.notify_all()

    async def subscribe(self, start: int = 0) -> AsyncIterator[DebateEvent]:
        i = max(start, 0)
        while True:
            async with self._cond:
                await self._cond.wait_for(lambda pos=i: pos < len(self.events) or self.finished)
                if i >= len(self.events):
                    return  # finished and fully drained
                event = self.events[i]
            i += 1
            yield event
