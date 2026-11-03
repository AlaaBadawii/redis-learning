"""Exercise 06: Sliding window rate limiter with Redis Sorted Sets.

Demonstrates:
- Using Redis Sorted Sets (ZSET) for accurate sliding window rate limiting.
- Atomic multi-command execution using Redis pipeline (MULTI/EXEC transaction).
- Pruning expired window entries with ZREMRANGEBYSCORE.
- Counting requests in the current active window with ZCARD.
- Setting key expiration (EXPIRE) to prevent Redis memory leaks for inactive clients.
- Configurable failure strategies: fail-open (allow traffic during Redis outages)
  vs. fail-closed (deny traffic when Redis is unavailable).
- Environment-aware connection configuration (REDIS_HOST, REDIS_PORT, REDIS_DB).
"""

import os
import time
import uuid

import redis
from redis.exceptions import RedisError

# Environment-aware connection configuration with defaults
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def rate_limit_key(identifier: str) -> str:
    """Return the namespaced Redis key for a given rate limit target."""
    return f"redis-learning:ratelimit:{identifier}"


def is_rate_limited(
    identifier: str,
    limit: int,
    window_seconds: int,
    redis_client: redis.Redis | None = None,
    fail_closed: bool = False,
    current_time: float | None = None,
) -> dict:
    """Check and record a request under a sliding window rate limit.

    Args:
        identifier: Unique client or resource identifier (e.g., user_id or IP).
        limit: Maximum number of allowed requests within the time window.
        window_seconds: Duration of the rolling window in seconds.
        redis_client: Optional Redis client override (defaults to module client).
        fail_closed: If True, reject requests when Redis is unavailable.
                     If False (default), allow requests when Redis fails (fail-open).
        current_time: Optional timestamp override (used for deterministic testing).

    Returns:
        dict with keys:
            - allowed (bool): True if request is allowed, False if limit exceeded or rejected.
            - current_requests (int): Requests recorded in current window.
            - remaining (int): Remaining requests before reaching limit (>= 0).
            - reset_seconds (int): Window duration in seconds until full reset.
            - error (str | None): Error message if Redis failure occurred.
    """
    if limit <= 0:
        return {
            "allowed": False,
            "current_requests": 0,
            "remaining": 0,
            "reset_seconds": window_seconds,
            "error": "Limit must be greater than zero",
        }

    if window_seconds <= 0:
        return {
            "allowed": False,
            "current_requests": 0,
            "remaining": 0,
            "reset_seconds": 0,
            "error": "Window must be greater than zero",
        }

    r = redis_client or client
    now = current_time if current_time is not None else time.time()
    window_start = now - window_seconds
    key = rate_limit_key(identifier)

    # Unique member identifier using timestamp + random uuid to allow multiple requests
    # within the exact same sub-millisecond timestamp.
    member = f"{now}:{uuid.uuid4().hex}"

    try:
        # Atomic sliding window evaluation using a MULTI/EXEC transaction pipeline.
        pipe = r.pipeline(transaction=True)
        # 1. Remove timestamps outside the sliding window.
        pipe.zremrangebyscore(key, "-inf", window_start)
        # 2. Count active requests within the window before inserting the new one.
        pipe.zcard(key)
        # 3. Add the current request timestamp with score = now.
        pipe.zadd(key, {member: now})
        # 4. Set TTL so inactive keys expire automatically and don't leak memory.
        pipe.expire(key, window_seconds + 1)
        results = pipe.execute()

        existing_count = results[1]

        if existing_count < limit:
            current_requests = existing_count + 1
            remaining = max(0, limit - current_requests)
            return {
                "allowed": True,
                "current_requests": current_requests,
                "remaining": remaining,
                "reset_seconds": window_seconds,
                "error": None,
            }
        else:
            # Limit exceeded: roll back the speculative zadd entry to prevent
            # blocked requests from artificially extending the window or counting.
            r.zrem(key, member)
            return {
                "allowed": False,
                "current_requests": existing_count,
                "remaining": 0,
                "reset_seconds": window_seconds,
                "error": None,
            }

    except RedisError as exc:
        if fail_closed:
            print(f"RATE LIMITER FAIL CLOSED ({type(exc).__name__}): {exc}")
            return {
                "allowed": False,
                "current_requests": 0,
                "remaining": 0,
                "reset_seconds": window_seconds,
                "error": str(exc),
            }
        else:
            print(f"RATE LIMITER FAIL OPEN ({type(exc).__name__}): {exc}")
            return {
                "allowed": True,
                "current_requests": 0,
                "remaining": limit,
                "reset_seconds": window_seconds,
                "error": str(exc),
            }


def main():
    demo_user = "user-123"
    limit = 3
    window = 2
    key = rate_limit_key(demo_user)

    try:
        client.ping()
        # Clean up any leftover keys from previous runs
        client.delete(key)

        print(f"=== Sliding Window Rate Limiter Demo (Limit: {limit} req / {window}s) ===")

        # 1. Send requests within the limit
        for i in range(1, limit + 1):
            res = is_rate_limited(demo_user, limit, window)
            print(
                f"Request {i}: allowed={res['allowed']}, "
                f"current={res['current_requests']}, remaining={res['remaining']}"
            )

        # 2. Exceed the limit
        blocked_res = is_rate_limited(demo_user, limit, window)
        print(
            f"Request {limit + 1} (Exceeded): allowed={blocked_res['allowed']}, "
            f"current={blocked_res['current_requests']}, remaining={blocked_res['remaining']}"
        )

        # 3. Wait for the window to slide and clear old entries
        print(f"\nWaiting {window + 0.1:.1f}s for the sliding window to reset...")
        time.sleep(window + 0.1)

        # 4. Request after window expiry should now succeed
        after_wait_res = is_rate_limited(demo_user, limit, window)
        print(
            f"Request after window reset: allowed={after_wait_res['allowed']}, "
            f"current={after_wait_res['current_requests']}, remaining={after_wait_res['remaining']}"
        )

        # 5. Check TTL semantics on the Sorted Set key
        key_ttl = client.ttl(key)
        print(f"Rate limit key TTL in Redis: {key_ttl} seconds")

    except RedisError as exc:
        print(f"Redis error: {type(exc).__name__}: {exc}")

    finally:
        try:
            client.delete(key)
        except RedisError as exc:
            print(f"Cleanup skipped: {type(exc).__name__}: {exc}")
        client.close()


if __name__ == "__main__":
    main()
