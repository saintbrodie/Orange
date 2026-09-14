# Personalization Release Smoke Test

Use this checklist after changing theme assets/runtime code or before a deployment upgrade that materially changes Personalization.

## Admin/runtime

- `/admin` loads and remains responsive during normal use.
- Repeatedly switching among General Settings, Tools, Personalization, Analytics, and Gallery does not freeze the page.
- Reloading `/admin` while Personalization was the last selected tab restores that tab after authentication.
- No `Script terminated by timeout` message appears.

The bundled Tailwind browser runtime may still print its known browser-build warning; that warning alone is not a Personalization failure.

## Presets

Verify each preset applies cleanly without console exceptions:

- Classic
- Cyber
- Princess
- Arcade
- Adventure
- Midnight
- Custom

Also verify:

- a previously saved `botanical` configuration migrates to Adventure
- Adventure uses the Orange topo background
- each preset's full mascot and compact/head asset are visually correct
- favicon/compact branding changes with the active preset
- Generate/loading treatment, background, radius, and palette update as expected
- reloading under a non-Classic theme does not visibly flash Classic first

Preset mascot files are ordinary editable SVGs under `static/theme-assets/logos/`. They do **not** need to preserve internal IDs, Illustrator class names, or other implementation-specific SVG markup. CI checks that the files exist and parse as SVG.

## White-label branding

- app name applies to the generator/admin presentation
- tagline applies where configured
- optional footer text applies
- primary PNG/JPEG/WebP logo upload works
- compact PNG/JPEG/WebP icon upload works
- removing uploaded branding restores the active preset assets
- custom colors, radius, and motion survive Save + reload

## Mobile

- Admin navigation includes Personalization
- the active Admin tab is reflected correctly in the mobile drawer
- generator tool selection remains usable after theme changes
- branding does not break generator layout at phone widths

## Regression tests

CI should remain green for:

- personalization validation/persistence
- Botanical -> Adventure migration
- preset manifest paths
- static theme SVG existence/parsing
- custom mode using Classic fallback assets
- theme asset endpoint compatibility aliases
- explicit personalization event integration
- protection against a document-wide theme MutationObserver
