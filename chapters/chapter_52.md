# Chapter 52 — Redis Pub/Sub for Scaling SSE

## Concepts You'll Learn
- Why in-memory queues do not scale (single-instance limitation)
- Redis Pub/Sub channels and the subscribe/publish model
- Per-user event channels
- Scaling real-time features across multiple application instances

## Concept Deep Dive

### Why In-Memory Queues Do Not Scale

The event bus you built in Chapter 51 uses `asyncio.Queue` objects stored in a Python dictionary. This works perfectly when you have a single application instance. But the moment you run multiple instances — which you will in production behind a load balancer — it breaks completely.

Imagine user Alice is connected via SSE to instance A, and user Bob triggers a notification for Alice from instance B. Instance B calls `event_bus.publish("alice", event)`, but Alice's queue only exists in instance A's memory. The event is lost. Each Python process has its own memory space, so in-memory state is invisible to other processes.

This is a fundamental distributed systems problem: shared mutable state across processes. The solution is to externalize the state to a system that all instances can access. Redis is the standard tool for this because it provides Pub/Sub (publish/subscribe) as a first-class feature with very low latency.

### Redis Pub/Sub

Redis Pub/Sub is a messaging system where publishers send messages to named channels, and subscribers receive messages from channels they are listening to. It is fire-and-forget — if nobody is subscribed to a channel when a message is published, the message is simply lost. There is no persistence, no replay, no acknowledgment. This makes it extremely fast but means it is only suitable for real-time delivery where missing a message is acceptable (you already have the notification in the database as a fallback).

```python
import redis.asyncio as redis

# Publisher side
r = redis.from_url("redis://localhost:6379")
await r.publish("user:abc123:events", json.dumps({"type": "notification", ...}))

# Subscriber side
pubsub = r.pubsub()
await pubsub.subscribe("user:abc123:events")
async for message in pubsub.listen():
    if message["type"] == "message":
        event = json.loads(message["data"])
        # deliver to SSE client
```

The key insight is that `pubsub.listen()` is an async iterator that blocks until a message arrives. This maps perfectly to your SSE generator pattern — instead of waiting on an `asyncio.Queue`, you wait on a Redis Pub/Sub subscription.

Redis Pub/Sub channels are lightweight. You can have millions of channels without significant memory overhead because channels are only materialized when someone subscribes. This means creating a unique channel per user (like `user:{user_id}:events`) is perfectly fine.

### Per-User Event Channels

The channel naming scheme `user:{user_id}:events` creates a dedicated communication pipe for each user. When any application instance needs to deliver a real-time event to a user, it publishes to that user's channel. Whichever instance holds the user's SSE connection has a subscriber on that channel and receives the message.

You can extend this pattern with additional channels for different scopes:
- `user:{user_id}:events` — personal notifications
- `manga:{manga_id}:events` — live updates for readers of a specific manga
- `global:events` — system-wide announcements

For MangaShelf, the per-user channel is sufficient. Each SSE connection subscribes to its user's channel. If a user has multiple devices connected (each to potentially different instances), each connection has its own subscriber on the same channel, and Redis delivers the message to all of them.

### Scaling Real-Time Across Multiple Instances

With Redis Pub/Sub in place, your real-time architecture looks like this:

```
Instance A                     Instance B
[SSE: Alice] <-- subscribe --> [Redis] <-- publish -- [API: Bob creates notification]
[SSE: Carol] <-- subscribe -->
```

Bob hits instance B's API endpoint to do something that triggers a notification for Alice. Instance B's NotificationService saves the notification to the database and publishes to `user:alice:events` on Redis. Redis delivers the message to instance A (which has a subscriber for Alice's channel). Instance A's SSE generator yields the event to Alice's browser.

This works regardless of how many instances you run. Each instance subscribes to channels for its connected users and publishes events for any user. Redis acts as the message broker in the middle.

One important nuance: each SSE connection needs its own Redis Pub/Sub connection. The `redis.asyncio` pubsub object enters a special subscription mode where it can only listen — it cannot be used for other Redis commands. This means you will have many Redis connections under load (one per SSE client). Redis handles this well (it supports tens of thousands of connections), but be aware of this scaling characteristic.

## Your Task

### Step 1: Create the Pub/Sub Service

Create `app/services/pubsub.py` with:
- A `RedisPubSub` class (or module-level functions) that wraps `redis.asyncio`
- `publish(channel: str, event: dict)` — serializes event to JSON and publishes to the channel
- `subscribe(channel: str)` — returns an async context manager or an object that yields messages. The caller should be able to iterate over incoming messages.
- Use the existing Redis connection URL from your app configuration

Consider this interface:

```python
class RedisPubSub:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)

    async def publish(self, channel: str, event: dict):
        await self.redis.publish(channel, json.dumps(event))

    async def subscribe(self, channel: str):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel)
        return pubsub  # caller iterates with pubsub.listen()

    async def unsubscribe(self, pubsub, channel: str):
        await pubsub.unsubscribe(channel)
        await pubsub.close()
```

### Step 2: Refactor the SSE Endpoint

Update `app/api/v1/endpoints/events.py` to use Redis Pub/Sub instead of the in-memory event bus:
- On connection, subscribe to `user:{user_id}:events` via the pubsub service
- The async generator listens on the pubsub subscription
- Heartbeat logic remains the same (send a comment every 15 seconds if no messages)
- On disconnect, unsubscribe and close the pubsub connection in the `finally` block

The generator loop should look something like:

```python
async def event_generator(user_id: str, pubsub_service: RedisPubSub):
    pubsub = await pubsub_service.subscribe(f"user:{user_id}:events")
    try:
        while True:
            message = await asyncio.wait_for(
                get_next_message(pubsub), timeout=15.0
            )
            if message:
                yield f"data: {message}\n\n"
    except asyncio.TimeoutError:
        yield ": heartbeat\n\n"
    # ... handle in a loop with heartbeat fallback
    finally:
        await pubsub_service.unsubscribe(pubsub, f"user:{user_id}:events")
```

Note: `pubsub.listen()` returns messages of different types. You only care about messages where `message["type"] == "message"` — the others are subscription confirmations.

### Step 3: Refactor NotificationService to Publish via Redis

Update `app/services/notification_service.py` to use the Redis pubsub service instead of the in-memory event bus:
- After saving a notification to the database, call `pubsub_service.publish(f"user:{user_id}:events", event_data)`
- The event data format stays the same as Chapter 51

### Step 4: Handle Pubsub Listener Properly

The `pubsub.listen()` async generator returns different message types:
- `subscribe` — confirmation that subscription succeeded
- `message` — actual data published to the channel
- `unsubscribe` — confirmation that unsubscription succeeded

Write a helper that wraps `pubsub.listen()` and only yields actual message data:

```python
async def listen_for_events(pubsub):
    async for message in pubsub.listen():
        if message["type"] == "message":
            yield json.loads(message["data"])
```

### Step 5: Remove the In-Memory Event Bus

Delete or deprecate `app/services/event_bus.py` from Chapter 51. All event delivery now goes through Redis. If you want to keep it as a fallback (for development without Redis), you can create an interface that both implementations satisfy.

### Step 6: Test Cross-Instance Delivery

To test that Redis Pub/Sub works across instances, run two copies of your application on different ports:

```bash
# Terminal 1
uvicorn app.main:app --port 8000

# Terminal 2
uvicorn app.main:app --port 8001

# Terminal 3: Connect SSE to instance 1
curl -N -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/events/stream

# Terminal 4: Create a notification via instance 2
curl -X POST http://localhost:8001/api/v1/... (trigger notification)
```

The notification created on port 8001 should appear in the SSE stream on port 8000.

## Expected Outcome
- SSE endpoint uses Redis Pub/Sub instead of in-memory queues
- Notifications published on any application instance are delivered to SSE connections on any other instance
- Heartbeats still work (every 15 seconds)
- Client disconnect properly cleans up Redis subscriptions
- Two app instances running simultaneously can deliver cross-instance events

## Hints
- The `redis.asyncio` pubsub `listen()` method is an async generator. You can iterate with `async for message in pubsub.listen()`.
- Be careful with `asyncio.wait_for` and the pubsub listener — you may need to wrap the iteration step in a coroutine to apply a timeout for heartbeats.
- Each pubsub connection is dedicated — you cannot reuse your main Redis connection for pubsub. Create a new Redis client specifically for pubsub operations.
- Consider creating the `RedisPubSub` instance as a singleton attached to the app state (in your lifespan handler) so it is shared across requests.

## What I'll Look For In Review
- Redis Pub/Sub properly replaces the in-memory event bus
- Subscription cleanup happens in every code path (normal exit, error, disconnect)
- Message type filtering (only processing "message" type, ignoring subscription confirmations)
- Per-user channel naming convention is consistent between publisher and subscriber
- The solution handles the case where Redis is temporarily unavailable (graceful degradation, not a crash)
