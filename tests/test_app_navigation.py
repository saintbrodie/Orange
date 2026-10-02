import unittest
from html.parser import HTMLParser
from unittest import mock

from fastapi.testclient import TestClient

from app.main import app


class NavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_navigation = False
        self.links = []
        self.link = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("aria-label") == "Main navigation":
            self.in_navigation = True
        elif self.in_navigation and tag == "a":
            self.link = {**attributes, "label": ""}

    def handle_data(self, data):
        if self.link is not None:
            self.link["label"] += data

    def handle_endtag(self, tag):
        if self.in_navigation and tag == "a" and self.link is not None:
            self.links.append(self.link)
            self.link = None
        elif self.in_navigation and tag in {"nav", "div"}:
            self.in_navigation = False


class AppNavigationTests(unittest.TestCase):
    def test_both_pages_offer_same_frame_navigation_without_admin_login(self):
        client = TestClient(app)
        with mock.patch("app.main.setup_required", return_value=False):
            for page in ("/", "/admin"):
                with self.subTest(page=page):
                    response = client.get(page)
                    self.assertEqual(response.status_code, 200)
                    parser = NavigationParser()
                    parser.feed(response.text)
                    self.assertEqual(
                        [(link["label"], link["href"]) for link in parser.links],
                        [("Generate", "/"), ("Admin", "/admin")],
                    )
                    for link in parser.links:
                        self.assertNotIn("target", link)
                        self.assertEqual(link.get("aria-current"), "page" if link["href"] == page else None)
                        destination = client.get(link["href"])
                        self.assertEqual(destination.status_code, 200)
                    self.assertIn('/static/app-navigation.css?v=1', response.text)
                    self.assertEqual(client.get("/static/app-navigation.css").status_code, 200)

    def test_navigation_destinations_still_require_initial_setup(self):
        client = TestClient(app)
        with mock.patch("app.main.setup_required", return_value=True):
            for page in ("/", "/admin"):
                with self.subTest(page=page):
                    response = client.get(page, follow_redirects=False)
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response.headers["location"], "/setup")

    def test_completed_setup_route_returns_to_generation(self):
        client = TestClient(app)
        with mock.patch("app.main.setup_required", return_value=False):
            response = client.get("/setup", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/")


if __name__ == "__main__":
    unittest.main()
