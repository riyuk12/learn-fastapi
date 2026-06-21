# Chapter 51 — Real-Time: Server-Sent Events

## Concepts You'll Learn
- SSE vs WebSocket (when to use which)
- StreamingResponse in FastAPI for SSE
- EventSource API on the client side
- Connection lifecycle and heartbeats

## Concept Deep Dive

### SSE vs WebSocket

Server-Sent Events (SSE) and WebSockets are both mechanisms for pushing data from server to client, but they serve different use cases and have very different complexity profiles.

**WebSockets** provide full-duplex communication — both client and server can send messages at any time. They use a custom protocol (ws://), require a dedicated connection upgrade handshake, and need custom reconnection logic. They are the right choice when you need bidirectional communication: chat applications, collaborative editing, multiplayer games.

**SSE** is unidirectional — only the server pushes data to the client. It uses plain HTTP, works through proxies and load balancers without special configuration, and the browser's `EventSource` API handles reconnection automatically. SSE is perfect for notifications, live feeds, progress updates — any scenario where the client only needs to *receive* real-time data.

For MangaShelf's notification system, SSE is the correct choice. Users do not need to send real-time messages to the server (they use regular HTTP endpoints for actions). They only need to *receive* notifications as they happen. SSE gives you this with dramatically less complexity than WebSockets.

```
WebSocket: Client <-----> Server  (bidirectional)
SSE:       Client <------ Server  (server push only)
```

One more practical advantage: SSE events are plain text with a simple format. Each event is a block of lines, where each line starts with a field name (`data:`, `event:`, `id:`, `retry:`). The browser parses this automatically.

### StreamingResponse in FastAPI

FastAPI (via Starlette) provides `StreamingResponse`, which accepts an async generator and streams its yielded values to the client as they are produced. For SSE, you set the content type to `text/event-stream` and yield events in the SSE format.

```python
from fastapi.responses import StreamingResponse

async def event_generator():
    while True:
        event = await get_next_event()  # blocks until event available
        yield f"data: {json.dumps(event)}\n\n"

@router.get("/events/stream")
async def sse_endpoint():
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
```

The SSE protocol requires each event to end with two newlines (`\n\n`). The `data:` field contains the payload. You can also include an `event:` field to name the event type (useful for client-side event filtering) and an `id:` field so the client can resume from where it left off if the connection drops.

The `Cache-Control: no-cache` header is essential — you do not want proxies or browsers caching your event stream. The `Connection: keep-alive` header tells intermediaries to keep the connection open.

### Connection Lifecycle and Heartbeats

SSE connections are long-lived HTTP connections. This creates lifecycle challenges you do not face with regular request/response endpoints.

**Client disconnect detection**: When a client closes the browser tab or loses network, the server does not immediately know. The TCP connection may linger. In FastAPI, you can detect disconnects by checking the ASGI `receive` channel or by catching `asyncio.CancelledError` when the generator is cancelled. Starlette will cancel your generator when the client disconnects.

**Heartbeats**: Proxies, load balancers, and browsers may close idle connections after a timeout (often 30-60 seconds). To prevent this, send a heartbeat (also called a "ping" or "keep-alive") at regular intervals. A heartbeat is a comment line in SSE format:

```python
# SSE comment line — browsers ignore it, but it keeps the connection alive
yield ": heartbeat\n\n"
```

The colon prefix makes it an SSE comment. The client's EventSource ignores it, but it keeps data flowing through the connection so intermediaries do not close it. A 15-second interval is a good default.

**Graceful shutdown**: When your server shuts down, you need to close all SSE connections cleanly. Your generator should handle cancellation and clean up resources (unsubscribe from queues, close connections). Wrap your event loop in a try/finally block.

```python
async def event_generator(user_id: str):
    queue = asyncio.Queue()
    register_listener(user_id, queue)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        unregister_listener(user_id, queue)
```

This pattern uses `asyncio.wait_for` to combine event waiting with heartbeat timing. If no event arrives within 15 seconds, the TimeoutError triggers a heartbeat. If the client disconnects, the CancelledError is caught and the listener is cleaned up.

## Your Task

### Step 1: Create an In-Memory Event Bus

Create `app/services/event_bus.py` with a simple in-memory pub/sub system:
- Maintain a dictionary of `user_id -> List[asyncio.Queue]` (a user might have multiple SSE connections from different devices)
- `subscribe(user_id) -> asyncio.Queue` — creates a queue, adds it to the user's list, returns it
- `unsubscribe(user_id, queue)` — removes the queue from the user's list
- `publish(user_id, event: dict)` — puts the event onto all queues for that user

This is intentionally simple and in-memory. Chapter 52 will replace it with Redis Pub/Sub for multi-instance scaling.

### Step 2: Create the SSE Endpoint

Create `app/api/v1/endpoints/events.py` with:
- `GET /events/stream` — requires authentication (get current user from token)
- Returns a `StreamingResponse` with `media_type="text/event-stream"`
- The async generator subscribes to the current user's event channel
- Yields events as `data: {json}\n\n` when they arrive
- Sends a heartbeat comment (`: heartbeat\n\n`) every 15 seconds if no events
- Cleans up the subscription on disconnect (in a `finally` block)

Add appropriate headers: `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no` (the last one tells Nginx not to buffer the stream — you will need this in Chapter 60).

### Step 3: Wire NotificationService to the Event Bus

Modify your `NotificationService` from Chapter 50. After creating a notification in the database, also publish it to the event bus:

```python
await event_bus.publish(user_id, {
    "type": "notification",
    "data": {
        "id": str(notification.id),
        "type": notification.type.value,
        "title": notification.title,
        "body": notification.body,
        "data": notification.data,
        "created_at": notification.created_at.isoformat()
    }
})
```

### Step 4: Add Event Types

Define a few event types that your SSE can deliver:
- `notification` — a new notification (most common)
- `unread_count` — updated unread notification count
- `chapter_update` — a new chapter was added to a followed manga

Format events with the SSE `event:` field so clients can listen selectively:

```
event: notification
data: {"id": "...", "title": "New chapter!", ...}

event: unread_count
data: {"count": 5}
```

### Step 5: Test with curl

The easiest way to test SSE is with curl:

```bash
curl -N -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/events/stream
```

The `-N` flag disables curl's output buffering. You should see heartbeat comments every 15 seconds and notification events when they are triggered.

### Step 6: Handle Edge Cases

- If the user token is invalid or expired, return a 401 before starting the stream (do not start streaming and then fail)
- If the server shuts down, the generator should exit cleanly
- Consider adding a maximum connection duration (e.g., 1 hour) after which the server closes the connection — the client's EventSource will auto-reconnect

## Expected Outcome
- `GET /events/stream` opens a long-lived SSE connection
- Heartbeats appear every 15 seconds as SSE comments
- When a notification is created for the connected user, it appears in the stream within milliseconds
- Client disconnect cleans up the subscription (no memory leak)
- curl can connect and receive events in real-time

## Hints
- Use `asyncio.wait_for(queue.get(), timeout=15.0)` to combine event waiting with heartbeat timing in a single loop.
- Remember that `StreamingResponse` expects an async generator (use `async def` with `yield`).
- For auth, extract the token from the Authorization header manually in the generator setup, or use your existing dependency before creating the StreamingResponse.
- The `X-Accel-Buffering: no` header is not needed for local dev, but add it now so it works when you add Nginx in Chapter 60.

## What I'll Look For In Review
- SSE format is correct (`data:` field, double newline terminators, comment heartbeats)
- Connection cleanup happens in a `finally` block, preventing resource leaks
- Heartbeat interval prevents proxy timeouts
- Authentication happens before the stream starts (no unauthenticated streaming)
- Event bus is cleanly separated from the SSE endpoint (easy to swap for Redis later)
