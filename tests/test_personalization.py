import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from app.api import personalization as personalization_api
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

    def test_legacy_botanical_theme_normalizes_to_adventure(self):
        payload = json.loads(json.dumps(personalization.DEFAULT_PERSONALIZATION))
        payload["theme"] = "botanical"
        normalized = personalization.validate_personalization(payload)
        self.assertEqual(normalized["theme"], "adventure")
        self.assertEqual(
            personalization.render_theme_svg("botanical", "head"),
            personalization.render_theme_svg("adventure", "head"),
        )

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

    def test_load_migrates_saved_botanical_theme(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "personalization.json")
            payload = json.loads(json.dumps(personalization.DEFAULT_PERSONALIZATION))
            payload["theme"] = "botanical"
            Path(target).write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(personalization, "PERSONALIZATION_PATH", target):
                loaded = personalization.load_personalization()
            self.assertEqual(loaded["theme"], "adventure")

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
        for theme in ("classic", "cyber", "princess", "arcade", "adventure", "midnight"):
            for kind in ("full", "head"):
                svg = personalization.render_theme_svg(theme, kind)
                ET.fromstring(svg)
                self.assertNotIn('href="../../', svg)
                self.assertIn("<svg", svg)

    def test_theme_mascots_preserve_geometry_and_add_identity(self):
        cyber = personalization.render_theme_svg("cyber", "head")
        princess = personalization.render_theme_svg("princess", "head")
        arcade = personalization.render_theme_svg("arcade", "full")
        adventure = personalization.render_theme_svg("adventure", "full")
        self.assertIn("orangeCyberScan", cyber)
        self.assertIn("orangeTwinkle", princess)
        self.assertIn("#00e5ff", arcade)
        self.assertIn("#c57a3c", adventure)

    def test_custom_uses_classic_mascot_geometry(self):
        self.assertEqual(
            personalization.render_theme_svg("custom", "head"),
            personalization.render_theme_svg("classic", "head"),
        )

    def test_preset_manifest_uses_real_theme_asset_route(self):
        root = Path(__file__).resolve().parents[1]
        presets = json.loads((root / "static" / "themes" / "presets.json").read_text(encoding="utf-8"))
        self.assertIn("adventure", presets)
        self.assertNotIn("botanical", presets)
        self.assertTrue((root / "static" / "theme-assets" / "adventure-topo.svg").is_file())
        for preset in presets.values():
            self.assertRegex(preset["mascot"], r"^/api/theme-assets/[a-z-]+/full\.svg$")
            self.assertRegex(preset["head"], r"^/api/theme-assets/[a-z-]+/head\.svg$")

    def test_theme_asset_routes_include_compatibility_alias(self):
        paths = {route.path for route in personalization_api.router.routes}
        self.assertIn("/api/theme-assets/{theme}/{kind}.svg", paths)
        self.assertIn("/api/theme-mascot/{theme}/{kind}", paths)
        response = personalization_api.get_theme_asset("classic", "head")
        self.assertEqual(response.media_type, "image/svg+xml")
        ET.fromstring(response.body.decode("utf-8"))

    def test_theme_runtime_does_not_watch_the_entire_document(self):
        runtime = (Path(__file__).resolve().parents[1] / "static" / "theme-runtime.js").read_text(encoding="utf-8")
        self.assertNotIn("observer.observe(document.documentElement", runtime)
        self.assertNotIn("subtree: true", runtime)

    def test_mobile_branding_uses_personalization_event(self):
        mobile = (Path(__file__).resolve().parents[1] / "static" / "mobile-navigation.js").read_text(encoding="utf-8")
        self.assertIn("orange:personalization-applied", mobile)
        self.assertIn("setAdminDrawerTitle", mobile)

    def test_mobile_tool_sync_only_observes_direct_child_replacement(self):
        mobile = (Path(__file__).resolve().parents[1] / "static" / "mobile-navigation.js").read_text(encoding="utf-8")
        self.assertIn("observer.observe(toolTabs, { childList: true })", mobile)
        self.assertNotIn("observer.observe(toolTabs, { childList: true, subtree: true", mobile)
        self.assertNotIn("attributeFilter: ['class'] });\n\n        return true;", mobile)


if __name__ == "__main__":
    unittest.main()
