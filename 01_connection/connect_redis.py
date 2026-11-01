"""Exercise 01: Connect to Redis from Python with redis-py.

Demonstrates:
- Creating a Redis client with explicit host, port, database,
  response decoding, and socket timeouts.
- Checking connectivity with PING.
- Storing, retrieving, and deleting a value.
- Understanding successful Redis responses.
- Cleaning up the client with try/finally.
"""

import redis
from redis.exceptions import RedisError

GREETING_KEY = "redis-learning:connection:greeting"


def main():
    print(f"redis-py version: {redis.__version__}")

    client = redis.Redis(
        host="localhost",
        port=6379,
        db=0,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )

    try:
        # 1. Check whether Python can communicate with Redis.
        print("PING:", client.ping())

        # 2. Store a value. SET returns True on success.
        result = client.set(GREETING_KEY, "Hello from Python")
        print("SET result:", result, type(result).__name__)

        # 3. Retrieve the value. GET returns None when the key is missing.
        value = client.get(GREETING_KEY)
        print("GET value:", value)
        print("GET type:", type(value).__name__)

        # 4. Clean up the test key. DELETE returns the number of keys removed.
        print("DELETE keys removed:", client.delete(GREETING_KEY))

    except RedisError as exc:
        print(f"Redis error: {type(exc).__name__}: {exc}")

    finally:
        client.close()
        print("Client closed.")


if __name__ == "__main__":
    main()
