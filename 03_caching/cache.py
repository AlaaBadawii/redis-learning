"""Exercise 03: Cache-aside (read-aside) with Redis.

The simulated DATABASE is the source of truth; Redis only stores
temporary copies. Demonstrates:
- Checking Redis before querying the database (cache hit vs. miss).
- JSON serialization and deserialization.
- TTL-based cache entries.
- Cache invalidation after the source of truth changes.
- Distinguishing a cache miss from Redis being unavailable: reads fall
  back to the database, because a cache is best-effort.
"""

import json

import redis
from redis.exceptions import RedisError

client = redis.Redis(
    host="localhost",
    port=6379,
    db=0,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)

# Simulated database — this dictionary is not the Redis cache.
DATABASE = {"42": {"id": 42, "name": "Ada", "role": "student"}}

CACHE_TTL_SECONDS = 60


def cache_key(user_id: str) -> str:
    return f"redis-learning:cache:users:{user_id}"


def get_user(user_id: str) -> dict | None:
    """Return the user as a dict, or None if it does not exist.

    Redis is a best-effort cache: if it is unavailable, read the
    database directly instead of failing the request.
    """
    key = cache_key(user_id)

    # 1. Try Redis first.
    try:
        cached = client.get(key)
    except RedisError as exc:
        # Distinct from a cache miss: Redis itself cannot be reached.
        print(f"REDIS UNAVAILABLE ({type(exc).__name__}): reading database directly")
        print(f"  detail: {exc}")
        return DATABASE.get(user_id)

    if cached is not None:
        print("CACHE HIT")
        return json.loads(cached)

    # 2. Cache miss: query the simulated database (source of truth).
    print("CACHE MISS — querying database")
    user = DATABASE.get(user_id)

    if user is not None:
        # 3. Cache the result for 60 seconds.
        try:
            client.set(key, json.dumps(user), ex=CACHE_TTL_SECONDS)
        except RedisError as exc:
            print(f"Unable to populate cache ({type(exc).__name__}): {exc}")

    return user


def update_user_role(user_id: str, new_role: str) -> bool:
    """Update the source of truth, then invalidate the cached copy."""
    user = DATABASE.get(user_id)
    if user is None:
        return False

    # Update the source of truth first.
    user["role"] = new_role

    # Invalidate the cached copy. DELETE does not require the key to
    # exist, so no existence check (and no extra round trip) is needed.
    try:
        client.delete(cache_key(user_id))
        print("CACHE INVALIDATED")
    except RedisError as exc:
        # The database is already updated; a stale copy may be served
        # until its TTL expires.
        print(
            f"WARNING: invalidation failed ({type(exc).__name__}): "
            "stale cache may be served until TTL expires"
        )
        print(f"  detail: {exc}")

    return True


def main():
    user_id = "42"

    try:
        client.ping()
        # Start with a clean cache for this exercise's key only.
        client.delete(cache_key(user_id))

        print("First request:")
        print(get_user(user_id))

        print("\nSecond request:")
        print(get_user(user_id))

        print("\nUpdate the user:")
        update_user_role(user_id, "admin")

        print("\nThird request (must reflect the update):")
        print(get_user(user_id))

        print("\nNonexistent user:")
        print(get_user("does_not_exist"))

    except RedisError as exc:
        print(f"Redis error: {type(exc).__name__}: {exc}")

    finally:
        try:
            client.delete(cache_key(user_id))
        except RedisError as exc:
            print(f"Cleanup skipped: {type(exc).__name__}: {exc}")
        client.close()


if __name__ == "__main__":
    main()
