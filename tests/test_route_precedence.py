import unittest

from app.main import app


class RoutePrecedenceTests(unittest.TestCase):
    def _first_endpoint_module(self, path: str, method: str):
        for route in app.routes:
            if getattr(route, "path", None) != path:
                continue
            methods = getattr(route, "methods", set()) or set()
            if method in methods:
                return route.endpoint.__module__
        return None

    def test_safe_generation_route_precedes_legacy_generate(self):
        self.assertEqual(
            self._first_endpoint_module("/api/generate", "POST"),
            "app.api.generation_v2",
        )

    def test_normalized_output_route_precedes_legacy_output(self):
        self.assertEqual(
            self._first_endpoint_module("/api/output", "GET"),
            "app.api.outputs",
        )


if __name__ == "__main__":
    unittest.main()
