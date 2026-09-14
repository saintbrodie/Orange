# Personalization browser diagnostics

The Personalization feature is intentionally event-driven. Avoid page-wide DOM observers in theme code: Orange already uses the Tailwind browser runtime, which watches DOM changes itself, so a self-triggering MutationObserver can cause repeated Tailwind rescans and freeze `/admin`.

## Expected console noise

The existing Tailwind browser build logs a production-use warning. Missing Lucide source maps may also appear in browser developer tools. Browser extensions can inject their own scripts and warnings. These messages do not by themselves indicate an Orange failure.

## Useful failure signals

Treat repeated Orange-script exceptions, failed `/api/personalization` requests, failed theme SVG requests, or browser `Script terminated by timeout` messages as actionable. If a timeout points into `tailwind.min.js`, inspect recent code for repeated DOM mutations rather than assuming Tailwind itself is the root cause.

## Runtime rule

Theme/branding changes should flow through the `orange:personalization-applied` event. Components that need to react to branding should listen for that event or read the current personalization state when they are created; they should not watch the entire document tree.
