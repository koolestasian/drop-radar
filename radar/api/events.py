"""In-process pub/sub for GET /api/stream (one process, so no broker).

The pipeline publishes ("opportunity", id) when an opportunity is first stored;
PATCH publishes ("action", id, user_id). Each stream filters for its own user.
"""
import asyncio
import json

QUEUE_SIZE = 200
KEEPALIVE_S = 15.0


class EventBus:
    def __init__(self):
        self._queues = set()

    def subscribe(self):
        queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue):
        self._queues.discard(queue)

    def publish(self, *event):
        for queue in list(self._queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # ponytail: a stalled client misses events; it refetches the feed on reconnect


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def stream(queue, user_id, render, disconnected, keepalive_s=KEEPALIVE_S):
    """Yield SSE frames for one user. `render(kind, opportunity_id)` returns the
    Opportunity dict this user may see for that event, or None to skip it."""
    yield "retry: 5000\n\n"
    while not await disconnected():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=keepalive_s)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
            continue
        kind, opportunity_id, *rest = event
        if kind == "action" and rest and rest[0] != user_id:
            continue
        payload = render(kind, opportunity_id)
        if payload is not None:
            yield sse(kind, payload)
