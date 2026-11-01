"""Exercise 04: JWT token blocklisting with Redis.

Demonstrates:
- Storing a revoked token's unique jti in Redis.
- Computing the remaining lifetime from its exp timestamp.
- Setting the blocklist key's TTL to the token's remaining lifetime.
- Checking whether a token identifier has been revoked.
- Handling already-expired tokens (no entry needed).
- Failing closed when the revocation status cannot be checked.

SECURITY NOTES:
- This exercise assumes the JWT's signature, issuer, audience, and
  expiration were already validated elsewhere, and only the claims
  (jti, exp) are passed in. A Redis blocklist does NOT replace
  signature or claim validation — it only adds revocation on top of
  them.
- Never store real JWTs here, only the unique token identifier (jti).
- A Redis error while checking the blocklist is NOT proof that a
  token is unrevoked: authentication must fail closed (deny the token).
"""

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


def blocklist_key(jti: str) -> str:
    return f"redis-learning:jwt:blocklist:{jti}"


def revoke_token(jti: str, exp: int) -> bool:
    """Store a revoked token identifier until the token would expire.

    Returns True if the blocklist entry was written, False if the
    token is already expired (no entry needed). Raises RedisError if
    Redis is unreachable — a failed revocation must not be reported
    as success.
    """
    remaining_seconds = exp - time.time()

    if remaining_seconds <= 0:
        print("Token already expired — no blocklist entry needed.")
        return False

    ttl = math.ceil(remaining_seconds)
    client.set(blocklist_key(jti), "revoked", ex=ttl)
    print(f"Token revoked. Blocklist TTL: {ttl} seconds")
    return True


def is_token_revoked(jti: str) -> bool:
    """Return True if the token identifier is in the blocklist.

    Raises RedisError when the blocklist cannot be checked. Callers
    must never interpret that error as "not revoked".
    """
    return bool(client.exists(blocklist_key(jti)))


def token_is_acceptable(jti: str) -> bool:
    """Fail-closed revocation check for an authentication path.

    Only returns True when Redis answered and the token is not
    blocklisted. If the status is unknown, the token is denied.
    """
    try:
        return not is_token_revoked(jti)
    except RedisError as exc:
        print(f"FAIL CLOSED: cannot check revocation ({type(exc).__name__}: {exc})")
        print("Denying the token because its status is unknown.")
        return False


def main():
    demo_jti = "demo-session-abc123"
    demo_exp = int(time.time()) + 120
    expired_jti = "demo-expired-token"

    try:
        client.ping()

        print("\n1. Check token before revocation:")
        print("   Revoked:", is_token_revoked(demo_jti))
        print("   Acceptable:", token_is_acceptable(demo_jti))

        print("\n2. Revoke token:")
        revoke_token(demo_jti, demo_exp)

        print("\n3. Check token after revocation:")
        print("   Revoked:", is_token_revoked(demo_jti))
        print("   Acceptable:", token_is_acceptable(demo_jti))

        print("\n4. Inspect remaining lifetime:")
        print("   TTL:", client.ttl(blocklist_key(demo_jti)), "seconds")

        print("\n5. Already-expired token:")
        result = revoke_token(expired_jti, int(time.time()) - 10)
        print("   revoke_token returned:", result)

    except RedisError as exc:
        print(f"Redis error: {type(exc).__name__}: {exc}")

    finally:
        # Clean up only the keys this exercise created.
        try:
            client.delete(blocklist_key(demo_jti), blocklist_key(expired_jti))
        except RedisError as exc:
            print(f"Cleanup skipped: {type(exc).__name__}: {exc}")
        client.close()


if __name__ == "__main__":
    main()
