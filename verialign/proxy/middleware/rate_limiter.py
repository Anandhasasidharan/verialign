import time
import threading
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 60
    tokens_per_minute: int = 100000


class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class RateLimiter:
    def __init__(self, default_config: RateLimitConfig | None = None) -> None:
        self.default_config = default_config or RateLimitConfig()
        self.buckets: dict[str, tuple[TokenBucket, TokenBucket]] = defaultdict(
            self._create_buckets
        )
        self._lock = threading.Lock()

    def _create_buckets(self) -> tuple[TokenBucket, TokenBucket]:
        return (
            TokenBucket(
                self.default_config.requests_per_minute,
                self.default_config.requests_per_minute / 60.0,
            ),
            TokenBucket(
                self.default_config.tokens_per_minute,
                self.default_config.tokens_per_minute / 60.0,
            ),
        )

    def check_limit(self, key: str, estimated_tokens: int = 1000) -> tuple[bool, dict]:
        req_bucket, token_bucket = self.buckets[key]

        req_allowed = req_bucket.consume(1)
        token_allowed = token_bucket.consume(estimated_tokens)

        allowed = req_allowed and token_allowed

        return allowed, {
            "requests_remaining": max(0, int(req_bucket.tokens)),
            "tokens_remaining": max(0, int(token_bucket.tokens)),
            "requests_limit": self.default_config.requests_per_minute,
            "tokens_limit": self.default_config.tokens_per_minute,
        }

    def get_headers(self, key: str, estimated_tokens: int = 1000) -> dict:
        allowed, info = self.check_limit(key, estimated_tokens)
        headers = {
            "X-RateLimit-Limit-Requests": str(info["requests_limit"]),
            "X-RateLimit-Remaining-Requests": str(info["requests_remaining"]),
            "X-RateLimit-Limit-Tokens": str(info["tokens_limit"]),
            "X-RateLimit-Remaining-Tokens": str(info["tokens_remaining"]),
            "X-RateLimit-Allowed": "true" if allowed else "false",
        }
        if not allowed:
            retry_after = str(max(1, int(60 / self.default_config.requests_per_minute)))
            headers["Retry-After"] = retry_after
        return headers


_global_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter()
    return _global_limiter


def set_rate_limiter(limiter: RateLimiter) -> None:
    global _global_limiter
    _global_limiter = limiter
