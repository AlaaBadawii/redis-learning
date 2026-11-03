"""Automated validation for the Redis learning exercises.

Runs against the local Redis server at localhost:6379. Safety rules:
- Never uses FLUSHDB / FLUSHALL.
- Never deletes keys it did not create.
- Every test cleans up exactly the keys it made (tearDown / finally).

Run with:
    python -m unittest discover -s tests -v
"""

import contextlib
import importlib.util
import io
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

import redis
from redis.exceptions import RedisError

ROOT = Path(__file__).resolve().parents[1]
# Nothing listens on this port (same idea as connection_error.py).
DEAD_PORT = 6390


def load_module(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dead_client() -> redis.Redis:
    return redis.Redis(
        host="localhost",
        port=DEAD_PORT,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


cache = load_module("exercise_cache", "03_caching/cache.py")
blocklist = load_module("exercise_blocklist", "04_token_blocklist/token_blocklist.py")
challenge = load_module("exercise_challenge", "05_final_challenge/final_challenge.py")
rate_limiter = load_module("exercise_rate_limiter", "06_rate_limiter/rate_limiter.py")


def capture_stdout(func, *args, **kwargs):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, buffer.getvalue()


class ScriptSmokeTests(unittest.TestCase):
    """Each exercise script must run end-to-end with exit code 0."""

    def run_script(self, relative_path: str, *expected_fragments: str) -> str:
        result = subprocess.run(
            [sys.executable, str(ROOT / relative_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"{relative_path} failed:\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        for fragment in expected_fragments:
            self.assertIn(fragment, result.stdout, f"{relative_path} output")
        return result.stdout

    def test_connect_redis(self):
        self.run_script(
            "01_connection/connect_redis.py",
            "PING: True",
            "GET value: Hello from Python",
            "DELETE keys removed: 1",
            "Client closed.",
        )

    def test_connection_error(self):
        self.run_script(
            "01_connection/connection_error.py",
            "Connection failed:",
            "GET missing key -> None",
            "a missing key returns None",
        )

    def test_operations(self):
        self.run_script(
            "02_operations/operations.py",
            "TTL without expiration: -1",
            "First increment: 1",
            "Second increment: 2",
            "Missing key: -2",
            "'name': 'Ada'",
        )

    def test_cache(self):
        self.run_script(
            "03_caching/cache.py",
            "CACHE MISS",
            "CACHE HIT",
            "CACHE INVALIDATED",
            "'role': 'admin'",
        )

    def test_token_blocklist(self):
        self.run_script(
            "04_token_blocklist/token_blocklist.py",
            "Revoked: False",
            "Token revoked. Blocklist TTL:",
            "Revoked: True",
            "revoke_token returned: False",
        )

    def test_final_challenge(self):
        self.run_script(
            "05_final_challenge/final_challenge.py",
            "First view:",
            "CACHE HIT",
            "CACHE INVALIDATED",
            "duration': 45",
            "Result: None",
            "Revoke expired token: False",
        )

    def test_rate_limiter(self):
        self.run_script(
            "06_rate_limiter/rate_limiter.py",
            "Sliding Window Rate Limiter Demo",
            "Request 1: allowed=True",
            "Request 4 (Exceeded): allowed=False",
            "Request after window reset: allowed=True",
            "Rate limit key TTL in Redis:",
        )


class CacheAsideTests(unittest.TestCase):
    def setUp(self):
        self.user_id = f"test-cache-{uuid.uuid4().hex}"
        self.key = cache.cache_key(self.user_id)
        cache.DATABASE[self.user_id] = {
            "id": self.user_id,
            "name": "Test User",
            "role": "student",
        }

    def tearDown(self):
        cache.DATABASE.pop(self.user_id, None)
        cache.client.delete(self.key)

    def test_miss_then_hit_returns_same_dict(self):
        first, first_out = capture_stdout(cache.get_user, self.user_id)
        second, second_out = capture_stdout(cache.get_user, self.user_id)

        self.assertIsInstance(first, dict)
        self.assertEqual(first, second)
        self.assertIn("CACHE MISS", first_out)
        self.assertIn("CACHE HIT", second_out)
        self.assertTrue(cache.client.exists(self.key))

    def test_invalidation_serves_updated_value(self):
        with contextlib.redirect_stdout(io.StringIO()):
            cache.get_user(self.user_id)
            updated = cache.update_user_role(self.user_id, "admin")
            refreshed = cache.get_user(self.user_id)

        self.assertTrue(updated)
        self.assertEqual(refreshed["role"], "admin")

        # The fresh value is now cached too.
        cached, _ = capture_stdout(cache.get_user, self.user_id)
        self.assertEqual(cached["role"], "admin")

    def test_nonexistent_user_returns_none_without_caching(self):
        missing_id = f"test-missing-{uuid.uuid4().hex}"
        result, _ = capture_stdout(cache.get_user, missing_id)

        self.assertIsNone(result)
        self.assertFalse(cache.client.exists(cache.cache_key(missing_id)))

    def test_update_nonexistent_user_returns_false(self):
        missing_id = f"test-missing-{uuid.uuid4().hex}"
        self.assertFalse(cache.update_user_role(missing_id, "admin"))

    def test_redis_unavailable_falls_back_to_database(self):
        original = cache.client
        cache.client = dead_client()
        try:
            user, output = capture_stdout(cache.get_user, self.user_id)
        finally:
            cache.client = original

        self.assertEqual(user["name"], "Test User")
        self.assertIn("REDIS UNAVAILABLE", output)

    def test_invalidation_failure_is_reported_not_silent(self):
        original = cache.client
        cache.client = dead_client()
        try:
            result, output = capture_stdout(
                cache.update_user_role, self.user_id, "admin"
            )
        finally:
            cache.client = original

        # The database (source of truth) was still updated.
        self.assertTrue(result)
        self.assertEqual(cache.DATABASE[self.user_id]["role"], "admin")
        self.assertIn("WARNING", output)


class TokenBlocklistTests(unittest.TestCase):
    def setUp(self):
        self.jti = f"test-jti-{uuid.uuid4().hex}"
        self.key = blocklist.blocklist_key(self.jti)

    def tearDown(self):
        blocklist.client.delete(self.key)

    def test_revoke_stores_key_with_remaining_lifetime(self):
        exp = int(time.time()) + 120
        result, _ = capture_stdout(blocklist.revoke_token, self.jti, exp)

        self.assertTrue(result)
        self.assertTrue(blocklist.is_token_revoked(self.jti))

        ttl = blocklist.client.ttl(self.key)
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, 120)

    def test_already_expired_token_is_not_blocklisted(self):
        result, _ = capture_stdout(
            blocklist.revoke_token, self.jti, int(time.time()) - 5
        )

        self.assertFalse(result)
        self.assertFalse(blocklist.client.exists(self.key))
        self.assertFalse(blocklist.is_token_revoked(self.jti))

    def test_fail_closed_when_blocklist_unavailable(self):
        original = blocklist.client
        blocklist.client = dead_client()
        try:
            with self.assertRaises(RedisError):
                blocklist.is_token_revoked(self.jti)
            acceptable, output = capture_stdout(blocklist.token_is_acceptable, self.jti)
        finally:
            blocklist.client = original

        self.assertFalse(acceptable)
        self.assertIn("FAIL CLOSED", output)


class FinalChallengeTests(unittest.TestCase):
    def setUp(self):
        # A test-only assessment id, distinct from the demo's 101.
        self.assessment_id = 888
        challenge.DATABASE[str(self.assessment_id)] = {
            "id": self.assessment_id,
            "title": "Test Assessment",
            "duration": 30,
        }
        self.views_key = challenge.assessment_views_key(self.assessment_id)
        self.cache_key = challenge.assessment_cache_key(self.assessment_id)
        challenge.client.delete(self.views_key, self.cache_key)

    def tearDown(self):
        challenge.DATABASE.pop(str(self.assessment_id), None)
        challenge.client.delete(self.views_key, self.cache_key)

    def test_view_counter_is_atomic_and_returns_int(self):
        first = challenge.record_assessment_view(self.assessment_id)
        second = challenge.record_assessment_view(self.assessment_id)

        self.assertEqual(first, 1)
        self.assertEqual(second, 2)
        self.assertIsInstance(second, int)

    def test_get_assessment_miss_then_hit_with_consistent_type(self):
        first, first_out = capture_stdout(
            challenge.get_assessment, self.assessment_id
        )
        second, second_out = capture_stdout(
            challenge.get_assessment, self.assessment_id
        )

        self.assertIsInstance(first, dict)
        self.assertEqual(first, second)
        self.assertIn("CACHE MISS", first_out)
        self.assertIn("CACHE HIT", second_out)

    def test_nonexistent_assessment_returns_none(self):
        result, _ = capture_stdout(challenge.get_assessment, 42424242)
        self.assertIsNone(result)

    def test_update_invalidates_cache_and_returns_new_value(self):
        with contextlib.redirect_stdout(io.StringIO()):
            challenge.get_assessment(self.assessment_id)  # populate cache
            updated = challenge.update_assessment_duration(self.assessment_id, 45)
            after = challenge.get_assessment(self.assessment_id)

        self.assertTrue(updated)
        self.assertIsInstance(after, dict)
        self.assertEqual(after["duration"], 45)

    def test_update_nonexistent_assessment_returns_false(self):
        self.assertFalse(challenge.update_assessment_duration(42424242, 10))

    def test_revoke_token_and_expired_token(self):
        jti = f"test-jti-{uuid.uuid4().hex}"
        key = challenge.token_blocklist_key(jti)
        try:
            result, _ = capture_stdout(
                challenge.revoke_token, jti, int(time.time()) + 120
            )
            self.assertTrue(result)
            self.assertTrue(challenge.client.exists(key))
            ttl = challenge.client.ttl(key)
            self.assertGreater(ttl, 0)
            self.assertLessEqual(ttl, 120)

            expired, _ = capture_stdout(
                challenge.revoke_token, f"{jti}-expired", int(time.time()) - 5
            )
            self.assertFalse(expired)
        finally:
            challenge.client.delete(key, challenge.token_blocklist_key(f"{jti}-expired"))

    def test_redis_unavailable_falls_back_to_database(self):
        original = challenge.client
        challenge.client = dead_client()
        try:
            assessment, output = capture_stdout(
                challenge.get_assessment, self.assessment_id
            )
        finally:
            challenge.client = original

        self.assertIsInstance(assessment, dict)
        self.assertEqual(assessment["title"], "Test Assessment")
        self.assertIn("REDIS UNAVAILABLE", output)

    def test_key_namespaces_do_not_collide(self):
        keys = {
            challenge.assessment_views_key(self.assessment_id),
            challenge.assessment_cache_key(self.assessment_id),
            challenge.token_blocklist_key(str(self.assessment_id)),
        }
        self.assertEqual(len(keys), 3)


class RateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.identifier = f"test-client-{uuid.uuid4().hex}"
        self.key = rate_limiter.rate_limit_key(self.identifier)

    def tearDown(self):
        rate_limiter.client.delete(self.key)

    def test_requests_within_limit_are_allowed(self):
        res1 = rate_limiter.is_rate_limited(self.identifier, limit=2, window_seconds=10)
        self.assertTrue(res1["allowed"])
        self.assertEqual(res1["current_requests"], 1)
        self.assertEqual(res1["remaining"], 1)

        res2 = rate_limiter.is_rate_limited(self.identifier, limit=2, window_seconds=10)
        self.assertTrue(res2["allowed"])
        self.assertEqual(res2["current_requests"], 2)
        self.assertEqual(res2["remaining"], 0)

    def test_exceeding_limit_is_rejected(self):
        rate_limiter.is_rate_limited(self.identifier, limit=1, window_seconds=10)
        res = rate_limiter.is_rate_limited(self.identifier, limit=1, window_seconds=10)

        self.assertFalse(res["allowed"])
        self.assertEqual(res["current_requests"], 1)
        self.assertEqual(res["remaining"], 0)
        self.assertIsNone(res["error"])

    def test_sliding_window_clears_old_requests(self):
        t0 = 1000.0
        # Send 2 requests at t0 with limit=2, window=5s
        res1 = rate_limiter.is_rate_limited(
            self.identifier, limit=2, window_seconds=5, current_time=t0
        )
        res2 = rate_limiter.is_rate_limited(
            self.identifier, limit=2, window_seconds=5, current_time=t0 + 1
        )
        self.assertTrue(res1["allowed"])
        self.assertTrue(res2["allowed"])

        # At t0 + 2, limit reached
        res3 = rate_limiter.is_rate_limited(
            self.identifier, limit=2, window_seconds=5, current_time=t0 + 2
        )
        self.assertFalse(res3["allowed"])

        # At t0 + 5.1, the first request at t0 has slid out of the 5s window
        res4 = rate_limiter.is_rate_limited(
            self.identifier, limit=2, window_seconds=5, current_time=t0 + 5.1
        )
        self.assertTrue(res4["allowed"])
        self.assertEqual(res4["current_requests"], 2)  # Request from t0+1 and t0+5.1

        # At t0 + 10.0, both earlier requests have expired
        res5 = rate_limiter.is_rate_limited(
            self.identifier, limit=2, window_seconds=5, current_time=t0 + 12.0
        )
        self.assertTrue(res5["allowed"])
        self.assertEqual(res5["current_requests"], 1)

    def test_key_ttl_is_set(self):
        rate_limiter.is_rate_limited(self.identifier, limit=5, window_seconds=10)
        ttl = rate_limiter.client.ttl(self.key)
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, 11)

    def test_invalid_parameters(self):
        zero_limit = rate_limiter.is_rate_limited(self.identifier, limit=0, window_seconds=10)
        self.assertFalse(zero_limit["allowed"])
        self.assertEqual(zero_limit["error"], "Limit must be greater than zero")

        zero_window = rate_limiter.is_rate_limited(self.identifier, limit=5, window_seconds=0)
        self.assertFalse(zero_window["allowed"])
        self.assertEqual(zero_window["error"], "Window must be greater than zero")

    def test_fail_open_when_redis_unavailable(self):
        original = rate_limiter.client
        rate_limiter.client = dead_client()
        try:
            res, output = capture_stdout(
                rate_limiter.is_rate_limited,
                self.identifier,
                limit=5,
                window_seconds=10,
                fail_closed=False,
            )
        finally:
            rate_limiter.client = original

        self.assertTrue(res["allowed"])
        self.assertIn("RATE LIMITER FAIL OPEN", output)
        self.assertIsNotNone(res["error"])

    def test_fail_closed_when_redis_unavailable(self):
        original = rate_limiter.client
        rate_limiter.client = dead_client()
        try:
            res, output = capture_stdout(
                rate_limiter.is_rate_limited,
                self.identifier,
                limit=5,
                window_seconds=10,
                fail_closed=True,
            )
        finally:
            rate_limiter.client = original

        self.assertFalse(res["allowed"])
        self.assertIn("RATE LIMITER FAIL CLOSED", output)
        self.assertIsNotNone(res["error"])


class ExpirationTests(unittest.TestCase):
    def test_key_expires_and_ttl_reports_minus_two(self):
        client = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        key = f"redis-learning:test:expire-{uuid.uuid4().hex}"
        try:
            client.set(key, "temporary", ex=1)
            ttl = client.ttl(key)
            self.assertGreater(ttl, 0)
            self.assertLessEqual(ttl, 1)

            time.sleep(1.1)

            self.assertIsNone(client.get(key))
            self.assertEqual(client.ttl(key), -2)
        finally:
            client.delete(key)
            client.close()


if __name__ == "__main__":
    unittest.main()
