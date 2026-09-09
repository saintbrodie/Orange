# Personalization and White-Label Branding

Orange keeps personalization on the deployment/admin side. It changes how Orange looks and is branded without adding controls to the Generate workflow.

## Preset themes

Orange ships with these presets:

- **Classic** — the original Orange appearance.
- **Cyber** — graphite, cyan/magenta, scanline effects, and a visor-equipped Orange.
- **Princess** — pink/lavender, sparkles, softer corners, and a crowned Orange.
- **Arcade** — saturated retro-game colors, pixel details, and pixel shades.
- **Botanical** — warm earth tones, sage accents, and a leaf detail.
- **Midnight** — near-black navy, restrained gold, stars, and a crescent detail.
- **Custom** — admin-selected color tokens and branding.

Preset definitions live in `static/themes/presets.json`. The theme runtime consumes the same manifest for the Generate page, Admin, and the Personalization preview.

## Mascot variants

The themed Orange mascots are not separate copies of the original artwork. Orange renders each variant from the current `static/orange.svg` and `static/orange-head.svg` geometry, then applies a preset palette and small theme-specific vector decorations.

This preserves the mascot identity and means future improvements to the base Orange geometry carry into the themed variants automatically.

The public asset endpoints are:

- `/api/theme-assets/<theme>/full.svg`
- `/api/theme-assets/<theme>/head.svg`

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

Preset manifests and runtime code remain tracked application files so Orange upgrades can add and improve built-in themes.

## Why there is no arbitrary CSS editor

Custom mode exposes structured design tokens instead of an unrestricted CSS field. This keeps personalization upgrade-safe and prevents an old deployment stylesheet from silently breaking the Generate page or mobile layout after Orange is updated.

If Orange later needs more customization, prefer adding another semantic theme token or icon role rather than exposing the entire frontend stylesheet.
