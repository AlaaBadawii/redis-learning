"""Exercise 02: Essential Redis operations.

Demonstrates:
- SET, GET, and DELETE.
- EXPIRE, TTL, and SET with an expiration (ex=...).
- INCR and atomic counters.
- Hashes with HSET, HGET, and HGETALL.
- The meaning of TTL values -1 (no expiration) and -2 (key does not exist).
"""

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

# Keep practice keys namespaced so they never collide with other data.
BASE = "redis-learning:ops"

MESSAGE_KEY = f"{BASE}:message"
EXPIRE_KEY = f"{BASE}:expire"
SET_EXPIRE_KEY = f"{BASE}:set-expire"
COUNTER_KEY = f"{BASE}:counter"
USER_KEY = f"{BASE}:user:42"
MISSING_KEY = f"{BASE}:does_not_exist"


def main():
    try:
        print("PONG:", client.ping())

        # 1. SET / GET
        client.set(MESSAGE_KEY, "Hello Redis!")
        print("\n1. SET / GET")
        print("Value:", client.get(MESSAGE_KEY))
        print("TTL without expiration:", client.ttl(MESSAGE_KEY))

        # 2. EXPIRE / TTL
        client.set(EXPIRE_KEY, "Temporary data")
        client.expire(EXPIRE_KEY, 30)
        print("\n2. EXPIRE / TTL")
        print("Value:", client.get(EXPIRE_KEY))
        print("Remaining time:", client.ttl(EXPIRE_KEY))

        # 3. SET with expiration — one atomic command instead of SET + EXPIRE.
        client.set(SET_EXPIRE_KEY, "Another temporary value", ex=40)
        print("\n3. SET with expiration (ex=40)")
        print("Value:", client.get(SET_EXPIRE_KEY))
        print("Remaining seconds:", client.ttl(SET_EXPIRE_KEY))

        # 4. INCR — atomic increment; creates the key starting at 0 if missing.
        print("\n4. INCR")
        print("First increment:", client.incr(COUNTER_KEY))
        print("Second increment:", client.incr(COUNTER_KEY))
        print("Stored value:", client.get(COUNTER_KEY))

        # 5. Hashes
        client.hset(
            USER_KEY,
            mapping={"name": "Ada", "role": "student"},
        )
        print("\n5. Hashes (HSET / HGET / HGETALL)")
        print("Name:", client.hget(USER_KEY, "name"))
        print("All fields:", client.hgetall(USER_KEY))

        # 6. Special TTL values.
        print("\n6. TTL special values")
        print("Persistent key (no expiration):", client.ttl(MESSAGE_KEY))
        print("Missing key:", client.ttl(MISSING_KEY))
        print("  -1 means the key exists but has no expiration.")
        print("  -2 means the key does not exist.")

    except RedisError as exc:
        print(f"Redis error: {type(exc).__name__}: {exc}")

    finally:
        # Clean up only the keys this exercise created.
        try:
            client.delete(
                MESSAGE_KEY,
                EXPIRE_KEY,
                SET_EXPIRE_KEY,
                COUNTER_KEY,
                USER_KEY,
            )
        except RedisError as exc:
            print(f"Cleanup skipped: {type(exc).__name__}: {exc}")
        client.close()


if __name__ == "__main__":
    main()
