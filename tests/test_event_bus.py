import asyncio
from pathlib import Path

from core.events import EventBus, SubagentCompleted, SubagentSpawned


def test_subscribe_and_publish_async_handler():
    bus = EventBus()
    received = []

    async def handler(event):
        received.append(event)

    async def _run():
        bus.subscribe(SubagentSpawned, handler)
        event = SubagentSpawned(subagent_type="analyzer", task_id="t1", workspace=Path("/tmp/w1"))
        bus.publish(event)
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert len(received) == 1
    assert received[0].subagent_type == "analyzer"


def test_publish_and_wait_awaits_all_handlers():
    bus = EventBus()
    received = []

    async def handler(event):
        await asyncio.sleep(0.01)
        received.append(event)

    async def _run():
        bus.subscribe(SubagentSpawned, handler)
        event = SubagentSpawned(subagent_type="analyzer", task_id="t2", workspace=Path("/tmp/w2"))
        await bus.publish_and_wait(event)

    asyncio.run(_run())
    assert len(received) == 1
    assert received[0].task_id == "t2"


def test_multiple_subscribers_same_event_type():
    bus = EventBus()
    received_a = []
    received_b = []

    async def handler_a(event):
        received_a.append(event)

    async def handler_b(event):
        received_b.append(event)

    async def _run():
        bus.subscribe(SubagentCompleted, handler_a)
        bus.subscribe(SubagentCompleted, handler_b)
        event = SubagentCompleted(
            subagent_type="writer", task_id="t3", success=True, summary="done"
        )
        await bus.publish_and_wait(event)

    asyncio.run(_run())
    assert len(received_a) == 1
    assert len(received_b) == 1
    assert received_a[0].success is True
    assert received_b[0].summary == "done"
