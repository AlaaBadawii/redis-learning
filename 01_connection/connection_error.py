"""Exercise 01: Handle Redis connection errors.

Demonstrates:
- Catching connection and timeout errors separately from other Redis
  errors, with fast failure via socket_connect_timeout / socket_timeout.
- The difference between "Redis is unreachable" (raises an exception)
  and "the key does not exist" (GET returns None). Never treat a
  connection failure as if it were an empty result.
"""

import redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

# Intentionally wrong port: nothing listens here, so every command fails.
bad_client = redis.Redis(
    host="localhost",
    port=6390,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)


def main():
    print("1. Connection failure (intentionally wrong port):")
    try:
        bad_client.ping()
        print("   Redis is available.")
    except RedisConnectionError as exc:
        print(f"   Connection failed: {exc}")
    except RedisTimeoutError as exc:
        print(f"   Redis timed out: {exc}")
    except RedisError as exc:
        print(f"   Redis operation failed: {exc}")
    finally:
        bad_client.close()

    print("\n2. Missing key vs connection failure (correct port):")
    client = redis.Redis(
        host="localhost",
        port=6379,
        db=0,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        client.ping()
        value = client.get("redis-learning:connection:does_not_exist")
        # A missing key is NOT an error: GET simply returns None.
        print(f"   GET missing key -> {value!r} (type: {type(value).__name__})")
        print("   Connection failure raises; a missing key returns None.")
    except RedisError as exc:
        print(f"   Redis error: {type(exc).__name__}: {exc}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
