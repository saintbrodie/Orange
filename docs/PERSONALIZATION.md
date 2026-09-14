# Personalization and White-Label Branding

Orange keeps personalization on the deployment/admin side. It changes how Orange looks and is branded without adding controls to the Generate workflow.

## Preset themes

Orange ships with these presets:

- **Classic** — the original Orange appearance.
- **Cyber** — old-school green terminal/CRT styling.
- **Princess** — dusty pink/lavender, softer corners, and playful details.
- **Arcade** — 1980s neon arcade styling.
- **Adventure** — topo-map trail styling with rust-orange highlights.
- **Midnight** — near-black navy with restrained gold accents.
- **Custom** — admin-selected color tokens and branding.

`Botanical` was the development name for Adventure. Existing saved `botanical` configurations are migrated automatically to `adventure` when loaded.

Preset definitions live in `static/themes/presets.json`. The theme runtime consumes the same manifest for the Generate page, Admin, and the Personalization preview. Adventure's contour background is stored as `static/theme-assets/adventure-topo.svg` and uses Orange's Adventure palette.

## Mascot variants

Each preset uses explicit, editable SVG assets under:

```text
static/theme-assets/logos/
  classic-full.svg
  classic-head.svg
  cyber-full.svg
  cyber-head.svg
  princess-full.svg
  princess-head.svg
  arcade-full.svg
  arcade-head.svg
  adventure-full.svg
  adventure-head.svg
  midnight-full.svg
  midnight-head.svg
```

These files are the source of truth for the built-in themed mascots. They can be edited in Illustrator, Inkscape, or another vector editor without preserving Orange-specific SVG IDs, class names, or implementation details. CI validates that the assets exist and remain parseable SVGs rather than depending on editor-specific markup.

The Classic assets mirror the standard Orange branding. Custom mode uses the Classic mascot unless an administrator uploads white-label branding.

The public compatibility asset endpoints are:

- `/api/theme-assets/<theme>/full.svg`
- `/api/theme-assets/<theme>/head.svg`
- `/api/theme-mascot/<theme>/<kind>`

## White-label branding

The Personalization tab can configure:

- app name
- tagline
- optional footer text
- primary logo
- compact icon / favicon
- custom accent, secondary accent, background, panel, text, and muted colors
- corner radius
- reduced, normal, or playful motion

A custom primary logo replaces the preset mascot. A custom compact icon replaces the preset head asset for the favicon/compact brand treatment.

Uploaded branding accepts PNG, JPEG, or WebP up to 3 MB and 4096 pixels in either dimension. Orange validates the image and strips metadata before storing it.

## Storage and upgrades

User-owned state is intentionally kept away from tracked application source:

```text
workflows/
  personalization.json
  branding/
    logo.png|jpg|webp
    icon.png|jpg|webp
```

Both locations are ignored by Git, so normal Orange updates do not overwrite local branding.

Preset manifests, theme SVGs, and runtime code remain tracked application files so Orange upgrades can add and improve built-in themes.

## Runtime behavior

Orange applies a small theme bootstrap from local storage before the page paints, which prevents a visible flash of the Classic theme after a different theme has been selected. The runtime then applies the authoritative saved personalization after startup.

Personalization changes emit the `orange:personalization-applied` event. Mobile navigation and other UI integrations listen to that event instead of watching the entire DOM. This avoids the MutationObserver feedback loop that previously caused Firefox/Tailwind freezes during development.

## Why there is no arbitrary CSS editor

Custom mode exposes structured design tokens instead of an unrestricted CSS field. This keeps personalization upgrade-safe and prevents an old deployment stylesheet from silently breaking the Generate page or mobile layout after Orange is updated.

If Orange later needs more customization, prefer adding another semantic theme token or icon role rather than exposing the entire frontend stylesheet.
