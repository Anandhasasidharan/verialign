import pytest

from verialign.proxy.middleware.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    TokenBucket,
)


class TestTokenBucket:
    def test_consume_tokens_available(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.consume(1) is True
        assert bucket.consume(5) is True

    def test_consume_tokens_exhausted(self) -> None:
        bucket = TokenBucket(capacity=2, refill_rate=0.0)
        assert bucket.consume(1) is True
        assert bucket.consume(1) is True
        assert bucket.consume(1) is False

    def test_refill_over_time(self) -> None:
        import time

        bucket = TokenBucket(capacity=10, refill_rate=10.0)  # 10 tokens/sec
        bucket.consume(10)
        assert bucket.consume(1) is False
        time.sleep(0.2)  # Wait for 2 tokens to refill
        assert bucket.consume(1) is True


class TestRateLimiter:
    def setup_method(self) -> None:
        self.limiter = RateLimiter(
            RateLimitConfig(requests_per_minute=10, tokens_per_minute=1000),
        )

    def test_check_limit_allows_within_limit(self) -> None:
        allowed, info = self.limiter.check_limit("client1", estimated_tokens=100)
        assert allowed is True
        assert info["requests_remaining"] == 9
        assert info["tokens_remaining"] == 900

    def test_check_limit_blocks_requests_over_limit(self) -> None:
        for _ in range(10):
            self.limiter.check_limit("client2", estimated_tokens=100)
        allowed, info = self.limiter.check_limit("client2", estimated_tokens=100)
        assert allowed is False
        assert info["requests_remaining"] == 0

    def test_check_limit_blocks_tokens_over_limit(self) -> None:
        for _ in range(10):
            self.limiter.check_limit(
                "client3",
                estimated_tokens=200,
            )  # 2000 tokens total > 1000 limit
        allowed, _info = self.limiter.check_limit("client3", estimated_tokens=100)
        assert allowed is False

    def test_different_clients_independent(self) -> None:
        for _ in range(10):
            self.limiter.check_limit("clientA")
        allowed_a, _ = self.limiter.check_limit("clientA")
        allowed_b, _ = self.limiter.check_limit("clientB")
        assert allowed_a is False
        assert allowed_b is True

    def test_get_headers(self) -> None:
        self.limiter.check_limit("client1", estimated_tokens=100)
        headers = self.limiter.get_headers("client1", estimated_tokens=100)
        assert "X-RateLimit-Limit-Requests" in headers
        assert "X-RateLimit-Remaining-Requests" in headers
        assert "X-RateLimit-Limit-Tokens" in headers
        assert "X-RateLimit-Remaining-Tokens" in headers
        assert "X-RateLimit-Allowed" in headers

    def test_check_limit_allows_with_api_key(self) -> None:
        allowed, info = self.limiter.check_limit(
            "client1",
            api_key="key-abc",
            estimated_tokens=100,
        )
        assert allowed is True
        assert info["requests_remaining"] == 9

    def test_check_limit_unknown_api_key_falls_back_to_ip(self) -> None:
        allowed, _info = self.limiter.check_limit(
            "client1",
            api_key=None,
            estimated_tokens=100,
        )
        assert allowed is True

    def test_valkey_key_not_available_falls_back(self) -> None:
        self.limiter._valkey = None
        allowed, _info = self.limiter.check_limit(
            "client1",
            api_key="key-abc",
            estimated_tokens=100,
        )
        assert allowed is True

    def test_key_config_passed_from_init(self) -> None:
        config = RateLimitConfig(
            key_requests_per_minute=500,
            key_tokens_per_minute=1_000_000,
        )
        limiter = RateLimiter(config)
        assert limiter.default_config.key_requests_per_minute == 500
        assert limiter.default_config.key_tokens_per_minute == 1_000_000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
