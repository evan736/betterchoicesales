"""
Server-Sent Events (SSE) endpoint for real-time updates across ORBIT.

Clients connect to GET /api/events/stream and receive typed events:
  - smart_inbox:new       — new inbound email processed
  - smart_inbox:updated   — email status changed / approved / rejected
  - smart_inbox:stats     — stats refresh
  - reshop:new            — new reshop detected
  - reshop:updated        — reshop stage/assignment changed
  - reshop:stats          — pipeline stats refresh
  - customers:updated     — customer data changed
  - sales:new             — new sale recorded
  - sales:updated         — sale status changed
  - dashboard:refresh     — general dashboard data changed
  - commission:updated    — commission data changed
  - chat:message          — internal team chat message

The event bus is in-memory (single-process). Each connected client gets
an asyncio.Queue. When an event is published, it's pushed to all queues.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Set
from datetime import datetime

from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/events", tags=["events"])

# ── In-memory event bus ──────────────────────────────────────────

class EventBus:
    """Simple pub/sub for SSE. Thread-safe via asyncio."""
    
    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
    
    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
        logger.info(f"SSE client connected (total: {len(self._subscribers)})")
        return queue
    
    async def unsubscribe(self, queue: asyncio.Queue):
        async with self._lock:
            self._subscribers.discard(queue)
        logger.info(f"SSE client disconnected (total: {len(self._subscribers)})")
    
    async def publish(self, event_type: str, data: Any = None):
        """Broadcast an event to all connected clients."""
        payload = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        }
        async with self._lock:
            dead_queues = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    dead_queues.append(queue)
            for q in dead_queues:
                self._subscribers.discard(q)
    
    def publish_sync(self, event_type: str, data: Any = None):
        """Synchronous publish — for use from sync code (API endpoints, schedulers, threads)."""
        payload = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        }
        # Try to use the running event loop (thread-safe)
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, push directly
            dead_queues = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(payload)
                except (asyncio.QueueFull, Exception):
                    dead_queues.append(queue)
            for q in dead_queues:
                self._subscribers.discard(q)
        except RuntimeError:
            # No running loop — we're in a background thread
            # Use call_soon_threadsafe to push to queues from the main loop
            try:
                loop = self._get_loop()
                if loop and loop.is_running():
                    for queue in list(self._subscribers):
                        loop.call_soon_threadsafe(self._safe_put, queue, payload)
                else:
                    # Fallback: direct push (may work in some scenarios)
                    for queue in list(self._subscribers):
                        try:
                            queue.put_nowait(payload)
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"SSE publish_sync from thread failed: {e}")

    @staticmethod
    def _safe_put(queue: asyncio.Queue, payload: dict):
        """Put item on queue, called via call_soon_threadsafe."""
        try:
            queue.put_nowait(payload)
        except (asyncio.QueueFull, Exception):
            pass

    def _get_loop(self):
        """Get the main event loop."""
        if not hasattr(self, '_loop'):
            self._loop = None
        return self._loop
    
    def set_loop(self, loop):
        """Store reference to the main event loop for thread-safe publishing."""
        self._loop = loop
    
    @property
    def client_count(self) -> int:
        return len(self._subscribers)


# Global singleton
event_bus = EventBus()


# ── SSE Endpoint ─────────────────────────────────────────────────

@router.get("/stream")
async def event_stream(request: Request):
    """SSE stream. Clients connect and receive real-time events.
    
    No auth required for now — events contain only IDs and counts, not PII.
    The frontend uses this to know WHEN to refetch, not to get the data itself.
    """
    # Capture the event loop for thread-safe publishing
    try:
        event_bus.set_loop(asyncio.get_running_loop())
    except Exception:
        pass
    
    queue = await event_bus.subscribe()
    
    async def generate():
        try:
            # Send initial connection event
            yield f"event: connected\ndata: {json.dumps({'status': 'ok', 'clients': event_bus.client_count})}\n\n"
            
            while True:
                try:
                    # Wait for events with timeout (keepalive)
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_type = payload.get("type", "update")
                    yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    yield f"event: ping\ndata: {json.dumps({'ts': datetime.utcnow().isoformat()})}\n\n"
                
                # Check if client disconnected
                if await request.is_disconnected():
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await event_bus.unsubscribe(queue)
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/clients")
async def connected_clients():
    """Debug: how many SSE clients are connected."""
    return {"clients": event_bus.client_count}
