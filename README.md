# Redis Python Learning Lab

A small, hands-on lab that demonstrates how to use **Redis from Python** (`redis-py`) in practical backend scenarios: connecting, running essential commands, caching, token revocation, and an integrated final challenge.

## Why this repository exists

This repository documents a backend engineer's learning path through Redis with Python. Each exercise is a small, runnable script that focuses on one real-world concern — not a production library or framework. The goal is to show that the basics are understood deliberately: correct response handling, error handling, cache consistency, TTL semantics, and security-aware token revocation.

## Concepts covered

- Creating a Redis client with explicit host, port, database, decoding, and timeouts
- Connectivity checks (`PING`) and client cleanup
- Distinguishing connection failures from missing keys
- `SET`, `GET`, `DELETE`, `EXPIRE`, `TTL`, `SET` with `ex=`
- Atomic counters with `INCR`
- Hash commands: `HSET`, `HGET`, `HGETALL`
- TTL semantics: `-1` (no expiration) vs `-2` (key does not exist)
- Cache-aside reads: hits, misses, JSON serialization, TTL, invalidation
- Graceful fallback when Redis is unavailable during reads
- JWT blocklisting by `jti` with a TTL derived from `exp`
- Fail-closed authentication when revocation status cannot be checked
- Sliding window rate limiting using Redis Sorted Sets (`ZSET`) and atomic multi-command pipelines
- Pruning expired window entries and dynamic TTL assignment to prevent memory leaks
- Configurable failure modes (fail-open vs fail-closed) during Redis downtime
- Distinct Redis key namespaces to avoid collisions

## Repository structure

```text
redis-learning/
│
├── README.md
├── requirements.txt
├── .gitignore
│
├── 01_connection/
│   ├── connect_redis.py        # Client setup, PING, SET/GET/DELETE, cleanup
│   └── connection_error.py     # Connection errors vs. missing keys
│
├── 02_operations/
│   └── operations.py           # Core commands, TTL, INCR, hashes
│
├── 03_caching/
│   └── cache.py                # Cache-aside pattern with invalidation
│
├── 04_token_blocklist/
│   └── token_blocklist.py      # JWT jti revocation with fail-closed checks
│
├── 05_final_challenge/
│   └── final_challenge.py      # Counter + cache + invalidation + revocation
│
├── 06_rate_limiter/
│   └── rate_limiter.py         # Sliding window rate limiter with Sorted Sets & pipeline
│
└── tests/
    └── test_exercises.py       # Automated validation (standard library)
```

## Prerequisites

- Python 3.10+
- A Redis server reachable at `localhost:6379`
  (this lab was tested against Redis 8.x running locally)
- `redis-py` 8.1.0 (pinned in `requirements.txt`)

## Installation and setup

```bash
git clone https://github.com/AlaaBadawii/redis-learning.git
cd redis-learning

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Make sure Redis is running:

```bash
redis-cli ping    # expect: PONG
```

## How to run each exercise

Run all commands from the repository root with the virtual environment activated.

### 01 — Connection

```bash
python 01_connection/connect_redis.py
python 01_connection/connection_error.py
```

**Expected behavior:**

- `connect_redis.py` prints the `redis-py` version, `PING: True`, the result of `SET`, the retrieved value, the number of deleted keys, and closes the client.
- `connection_error.py` shows a connection failure against an intentionally wrong port (fast failure via socket timeouts), then shows that a *missing key* on the correct port returns `None` instead of raising.

### 02 — Essential operations

```bash
python 02_operations/operations.py
```

**Expected behavior:**

- Prints `PONG`, values for `SET`/`GET`, TTLs from `EXPIRE` and `SET ... ex=40`
- Counter increments (`1`, `2`) via `INCR`
- Hash fields via `HSET`/`HGET`/`HGETALL`
- TTL `-1` for a persistent key and `-2` for a missing key
- Cleans up only the keys it created, then exits

### 03 — Caching

```bash
python 03_caching/cache.py
```

**Expected behavior:**

- First read: `CACHE MISS` → simulated database → cached for 60 seconds
- Second read: `CACHE HIT`
- After updating the role: `CACHE INVALIDATED`, then a fresh miss returning the updated value
- A nonexistent user returns `None`

### 04 — Token blocklist

```bash
python 04_token_blocklist/token_blocklist.py
```

**Expected behavior:**

- `is_token_revoked` returns `False` before revocation and `True` after
- `revoke_token` writes the `jti` with a TTL equal to the token's remaining lifetime
- An already-expired token returns `False` (no blocklist entry written)
- `token_is_acceptable` demonstrates fail-closed behavior when the status cannot be checked

### 05 — Final challenge

```bash
python 05_final_challenge/final_challenge.py
```

**Expected behavior:**

1. View counter: `INCR` returns `1`, then `2`
2. First read: `CACHE MISS` → database → cached; second read: `CACHE HIT` (same dict both times)
3. Updating the duration invalidates the cache; the next read returns the new value
4. A nonexistent assessment returns `None`
5. `revoke_token` returns `True` with a TTL near 120 seconds; an expired token returns `False`

### 06 — Sliding window rate limiter

```bash
python 06_rate_limiter/rate_limiter.py
```

**Expected behavior:**

- Demonstrates a rolling sliding window rate limiter backed by Redis Sorted Sets (`ZSET`).
- Uses atomic pipeline execution (`MULTI/EXEC`) to prune expired timestamps, count active requests, record new timestamps, and refresh key TTLs.
- Requests within the threshold return `allowed=True` with accurate `remaining` counts.
- Excess requests return `allowed=False` without incrementing or leaking memory.
- Requests succeed once the sliding window has elapsed.
- Handles Redis outages with configurable failure behavior (`fail_open` vs `fail_closed`).

## Running the tests

The test suite uses only the Python standard library (`unittest`) and runs against your local Redis server. It isolates its own keys and cleans up exactly what it creates — it never calls `FLUSHDB`/`FLUSHALL` and never touches unrelated keys.

```bash
python -m unittest discover -s tests -v
```

## Important Redis concepts demonstrated

| Concept | Where |
|---|---|
| Client configuration & timeouts | `01_connection/` |
| Connection error vs. `None` for missing keys | `01_connection/connection_error.py` |
| Atomic `INCR` counters | `02_operations/`, `05_final_challenge/` |
| TTL semantics (`-1`, `-2`) and `ex=` | `02_operations/operations.py` |
| Hashes as compact records | `02_operations/operations.py` |
| Cache-aside read path (hit/miss) | `03_caching/cache.py` |
| Cache invalidation (write-through to DB, delete cache) | `03_caching/`, `05_final_challenge/` |
| Best-effort caching when Redis is down | `03_caching/cache.py`, `05_final_challenge/` |
| TTL-expiring blocklist entries | `04_token_blocklist/`, `05_final_challenge/` |
| Fail-closed revocation checks | `04_token_blocklist/token_blocklist.py` |
| Key namespacing to prevent collisions | all exercises |
| Sliding window rate limiting with Sorted Sets (`ZSET`) | `06_rate_limiter/rate_limiter.py` |
| Atomic transactions via pipeline (`MULTI/EXEC`) | `06_rate_limiter/rate_limiter.py` |
| Configurable fail-open vs fail-closed strategy | `06_rate_limiter/rate_limiter.py` |

## Limitations and production considerations

This is an **educational lab**, not production-ready software. Before using any of these patterns in production, consider:

- **No authentication or TLS.** The examples connect to an unauthenticated local Redis. Production deployments should require auth (`requirepass`/ACLs), TLS, and network isolation.
- **No connection pooling tuning.** `redis-py` pools connections by default, but production apps need pooling, retry, and backoff strategies suited to their traffic.
- **Cache consistency is best-effort.** Invalidation can fail (handled here with a warning); production systems may need TTLs sized to the staleness budget, versioned keys, or pub/sub invalidation.
- **Single instance, no clustering.** No Sentinel, Cluster, or replication is covered — fine for learning, insufficient for high availability.
- **JWT blocklisting is only one layer.** It complements — never replaces — signature, issuer, audience, and expiration validation. It also introduces a Redis dependency into authentication: production designs must decide explicitly whether auth fails open or closed when the blocklist is unreachable (this lab fails closed).
- **No eviction/persistence strategy.** Production Redis needs a deliberate `maxmemory-policy`, persistence choices, and capacity planning.
- **Key cleanup relies on script exit.** Each script deletes only its own keys in `finally`; in production, TTLs (already used here) are the reliable cleanup mechanism.
