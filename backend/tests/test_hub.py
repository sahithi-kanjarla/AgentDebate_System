import asyncio

from app.debate.hub import DebateChannel
from app.schemas import DebateEvent


def ev(seq: int) -> DebateEvent:
    return DebateEvent(seq=seq, type="agent_thinking", data={"n": seq})


async def drain(channel: DebateChannel, start: int = 0) -> list[int]:
    return [e.seq async for e in channel.subscribe(start)]


async def test_late_subscriber_gets_history_then_live_events():
    ch = DebateChannel()
    for i in range(3):
        await ch.publish(ev(i))
    task = asyncio.create_task(drain(ch))
    await asyncio.sleep(0.01)  # subscriber has consumed the backlog and is waiting
    for i in range(3, 6):
        await ch.publish(ev(i))
    await ch.finish()
    assert await task == [0, 1, 2, 3, 4, 5]


async def test_subscribe_from_offset_and_after_finish():
    ch = DebateChannel()
    for i in range(4):
        await ch.publish(ev(i))
    await ch.finish()
    assert await drain(ch, 2) == [2, 3]
    assert await drain(ch, 99) == []


async def test_multiple_subscribers_do_not_interfere():
    ch = DebateChannel()
    tasks = [asyncio.create_task(drain(ch)) for _ in range(3)]
    for i in range(5):
        await ch.publish(ev(i))
        await asyncio.sleep(0)
    await ch.finish()
    assert [await t for t in tasks] == [[0, 1, 2, 3, 4]] * 3


async def test_cancelled_subscriber_does_not_break_others():
    ch = DebateChannel()
    doomed = asyncio.create_task(drain(ch))
    survivor = asyncio.create_task(drain(ch))
    await asyncio.sleep(0.01)
    doomed.cancel()
    await ch.publish(ev(0))
    await ch.finish()
    assert await survivor == [0]
