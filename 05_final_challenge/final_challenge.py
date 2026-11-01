"""Exercise 05: Final integrated challenge.

Combines the skills from the previous exercises:
- Atomic view counters with INCR.
- Cache-aside reads with a 60-second TTL.
- Cache invalidation after updating the source of truth.
- JWT blocklisting with a TTL derived from the token's lifetime.

Distinct Redis key namespaces (they can never collide):
- counter:   redis-learning:assessment:{id}:views
- cache:     redis-learning:assessment:{id}:cached
- blocklist: redis-learning:jwt:blocklist:{jti}
"""

import json
import math
import time

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

# Simulated database — the source of truth for assessments.
DATABASE = {"101": {"id": 101, "title": "Python Fundamentals", "duration": 30}}

CACHE_TTL_SECONDS = 60


def assessment_views_key(assessment_id: int) -> str:
    return f"redis-learning:assessment:{assessment_id}:views"


def assessment_cache_key(assessment_id: int) -> str:
    return f"redis-learning:assessment:{assessment_id}:cached"


def token_blocklist_key(jti: str) -> str:
    return f"redis-learning:jwt:blocklist:{jti}"


def record_assessment_view(assessment_id: int) -> int:
    """Atomically increment and return the view count for an assessment.

    INCR is atomic on the Redis server, so concurrent increments never
    lose updates. Raises RedisError if Redis is unreachable.
    """
    return client.incr(assessment_views_key(assessment_id))


def get_assessment(assessment_id: int) -> dict | None:
    """Return the assessment as a dict, or None if it does not exist.

    Redis is a best-effort cache: if it is unavailable, read the
    database directly instead of failing the request. The returned
    value is a plain dict regardless of where it came from.
    """
    cache_key = assessment_cache_key(assessment_id)

    # 1. Check Redis first.
    try:
        cached = client.get(cache_key)
    except RedisError as exc:
        print(f"REDIS UNAVAILABLE ({type(exc).__name__}): reading database directly")
        print(f"  detail: {exc}")
        return DATABASE.get(str(assessment_id))

    if cached is not None:
        print("CACHE HIT")
        return json.loads(cached)

    # 2. Cache miss: query the simulated database (source of truth).
    print("CACHE MISS — querying database")
    assessment = DATABASE.get(str(assessment_id))

    if assessment is not None:
        # 3. Cache existing records for 60 seconds.
        try:
            client.set(cache_key, json.dumps(assessment), ex=CACHE_TTL_SECONDS)
        except RedisError as exc:
            print(f"Unable to populate cache ({type(exc).__name__}): {exc}")

    return assessment


def update_assessment_duration(assessment_id: int, duration: int) -> bool:
    """Update the database, then drop the stale cache entry.

    Returns False when the assessment does not exist. DELETE does not
    require the key to exist, so no existence check is needed (checking
    would only add a wasted round trip).
    """
    assessment = DATABASE.get(str(assessment_id))
    if assessment is None:
        return False

    # 1. Update the source of truth.
    assessment["duration"] = duration

    # 2. Invalidate the cached copy.
    try:
        client.delete(assessment_cache_key(assessment_id))
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


def revoke_token(jti: str, exp: int) -> bool:
    """Blocklist a token identifier until its original expiry.

    Returns True if the blocklist entry was written, False if the
    token has already expired. Raises RedisError if Redis is
    unreachable — revocation failure must never be treated as success.

    Assumes the JWT's signature and claims were already validated
    elsewhere; this only adds revocation on top of that validation.
    """
    remaining_seconds = exp - time.time()

    if remaining_seconds <= 0:
        print("Token already expired — no blocklist entry needed.")
        return False

    ttl = math.ceil(remaining_seconds)
    client.set(token_blocklist_key(jti), "revoked", ex=ttl)
    print(f"Token revoked. Blocklist TTL: {ttl} seconds")
    return True


def main():
    assessment_id = 101
    jti = "demo-final-challenge-jti"
    expired_jti = "demo-final-challenge-expired"

    views_key = assessment_views_key(assessment_id)
    cache_key = assessment_cache_key(assessment_id)
    block_key = token_blocklist_key(jti)
    expired_block_key = token_blocklist_key(expired_jti)

    try:
        client.ping()
        # Start from a clean state — only this exercise's keys.
        client.delete(views_key, cache_key, block_key, expired_block_key)

        print("=== 1. Assessment view counter (INCR) ===")
        print("First view: ", record_assessment_view(assessment_id))
        print("Second view:", record_assessment_view(assessment_id))

        print("\n=== 2. Assessment cache (cache-aside) ===")
        print("First read: ", get_assessment(assessment_id))
        print("Second read:", get_assessment(assessment_id))

        print("\n=== 3. Cache invalidation ===")
        print("Update result:", update_assessment_duration(assessment_id, 45))
        print("Read after update:", get_assessment(assessment_id))

        print("\n=== 4. Nonexistent assessment ===")
        print("Result:", get_assessment(999))

        print("\n=== 5. Token revocation ===")
        print("Revoke:", revoke_token(jti, int(time.time()) + 120))
        print("Blocklist TTL:", client.ttl(block_key), "seconds")
        print("Revoke expired token:", revoke_token(expired_jti, int(time.time()) - 10))

    except RedisError as exc:
        print(f"Redis error: {type(exc).__name__}: {exc}")

    finally:
        # Clean up only the keys this exercise created.
        try:
            client.delete(views_key, cache_key, block_key, expired_block_key)
        except RedisError as exc:
            print(f"Cleanup skipped: {type(exc).__name__}: {exc}")
        client.close()


if __name__ == "__main__":
    main()
