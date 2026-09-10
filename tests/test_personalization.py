import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from app.core import personalization


class PersonalizationTests(unittest.TestCase):
    def test_default_personalization_is_classic(self):
        with patch.object(personalization, "PERSONALIZATION_PATH", os.path.join(tempfile.gettempdir(), "orange-no-such-personalization.json")):
            config = personalization.load_personalization()
        self.assertEqual(config["theme"], "classic")
        self.assertEqual(config["branding"]["appName"], "Orange")

    def test_valid_custom_theme_normalizes_colors(self):
        config = personalization.validate_personalization(
            {
                "theme": "custom",
                "branding": {"appName": "Acme AI", "tagline": "Creative Tools", "footerText": "Internal"},
                "custom": {
                    "accent": "#ABCDEF",
                    "accentSecondary": "#123456",
                    "background": "#010203",
                    "panel": "#111111",
                    "text": "#FFFFFF",
                    "muted": "#777777",
                    "radius": 12,
                    "motion": "playful",
                },
            }
        )
        self.assertEqual(config["custom"]["accent"], "#abcdef")
        self.assertEqual(config["branding"]["appName"], "Acme AI")
        self.assertEqual(config["custom"]["radius"], 12)

    def test_unknown_theme_is_rejected(self):
        with self.assertRaises(ValueError):
            personalization.validate_personalization({"theme": "matrix"})

    def test_bad_color_is_rejected(self):
        payload = json.loads(json.dumps(personalization.DEFAULT_PERSONALIZATION))
        payload["theme"] = "custom"
        payload["custom"]["accent"] = "orange"
        with self.assertRaises(ValueError):
            personalization.validate_personalization(payload)

    def test_radius_is_bounded(self):
        payload = json.loads(json.dumps(personalization.DEFAULT_PERSONALIZATION))
        payload["custom"]["radius"] = 99
        with self.assertRaises(ValueError):
            personalization.validate_personalization(payload)

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "personalization.json")
            with patch.object(personalization, "PERSONALIZATION_PATH", target):
                saved = personalization.save_personalization(
                    {
                        "theme": "midnight",
                        "branding": {"appName": "Night Lab", "tagline": "", "footerText": ""},
                        "custom": personalization.DEFAULT_PERSONALIZATION["custom"],
                    }
                )
                loaded = personalization.load_personalization()
            self.assertEqual(saved, loaded)
            self.assertEqual(loaded["theme"], "midnight")
            self.assertEqual(loaded["branding"]["appName"], "Night Lab")

    def test_branding_lookup_and_clear(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(personalization, "BRANDING_DIR", temp_dir):
                logo = os.path.join(temp_dir, "logo.png")
                with open(logo, "wb") as handle:
                    handle.write(b"placeholder")
                self.assertEqual(personalization.branding_path("logo"), logo)
                personalization.clear_branding("logo")
                self.assertIsNone(personalization.branding_path("logo"))

    def test_all_preset_mascots_are_self_contained_valid_svg(self):
        for theme in ("classic", "cyber", "princess", "arcade", "botanical", "midnight"):
            for kind in ("full", "head"):
                svg = personalization.render_theme_svg(theme, kind)
                ET.fromstring(svg)
                self.assertNotIn('href="../../', svg)
                self.assertIn("<svg", svg)

    def test_theme_mascots_preserve_geometry_and_add_identity(self):
        cyber = personalization.render_theme_svg("cyber", "head")
        princess = personalization.render_theme_svg("princess", "head")
        self.assertIn("#22d3ee", cyber)
        self.assertIn("orangeCyberScan", cyber)
        self.assertIn("#f472b6", princess)
        self.assertIn("orangeTwinkle", princess)

    def test_custom_uses_classic_mascot_geometry(self):
        self.assertEqual(
            personalization.render_theme_svg("custom", "head"),
            personalization.render_theme_svg("classic", "head"),
        )

    def test_theme_runtime_does_not_watch_the_entire_document(self):
        """A DOM-wide observer can self-trigger and make Tailwind rescan forever."""
        runtime = (Path(__file__).resolve().parents[1] / "static" / "theme-runtime.js").read_text(encoding="utf-8")
        self.assertNotIn("observer.observe(document.documentElement", runtime)
        self.assertNotIn("subtree: true", runtime)

    def test_mobile_branding_uses_personalization_event(self):
        mobile = (Path(__file__).resolve().parents[1] / "static" / "mobile-navigation.js").read_text(encoding="utf-8")
        self.assertIn("orange:personalization-applied", mobile)
        self.assertIn("setAdminDrawerTitle", mobile)


if __name__ == "__main__":
    unittest.main()
