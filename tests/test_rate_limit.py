import unittest

from app.core.rate_limit import SlidingWindowRateLimiter


class SlidingWindowRateLimiterTests(unittest.TestCase):
    def test_denies_after_limit(self):
        limiter = SlidingWindowRateLimiter()
        self.assertTrue(limiter.allow("client", 2, 60))
        self.assertTrue(limiter.allow("client", 2, 60))
        self.assertFalse(limiter.allow("client", 2, 60))

    def test_clients_have_independent_buckets(self):
        limiter = SlidingWindowRateLimiter()
        self.assertTrue(limiter.allow("a", 1, 60))
        self.assertFalse(limiter.allow("a", 1, 60))
        self.assertTrue(limiter.allow("b", 1, 60))

    def test_zero_limit_disables_limiter(self):
        limiter = SlidingWindowRateLimiter()
        for _ in range(100):
            self.assertTrue(limiter.allow("client", 0, 60))

    def test_reset_clears_bucket(self):
        limiter = SlidingWindowRateLimiter()
        self.assertTrue(limiter.allow("client", 1, 60))
        self.assertFalse(limiter.allow("client", 1, 60))
        limiter.reset()
        self.assertTrue(limiter.allow("client", 1, 60))


if __name__ == "__main__":
    unittest.main()
