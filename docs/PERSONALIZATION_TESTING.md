# Personalization test checklist

Before merging the Personalization branch, verify:

- `/admin` loads and remains responsive for at least a minute.
- Switching repeatedly among General Settings, Tool Editor, Personalization, Analytics, and Gallery does not freeze the page.
- Reloading `/admin` while Personalization was the last selected tab restores the Personalization tab after authentication.
- Each preset applies without console exceptions: Classic, Cyber, Princess, Arcade, Adventure, Midnight, Custom.
- A previously saved `botanical` personalization loads as Adventure without breaking the page.
- Adventure uses the source-derived topo vector background with the Orange Adventure palette.
- Theme mascot, favicon, Generate/loading icon, background treatment, radius, and colors change as expected.
- App name, tagline, and optional footer apply to the generator.
- Primary logo and compact icon uploads work for PNG, JPEG, and WebP; removing them restores the preset mascot/icon.
- Custom colors, radius, and motion persist after Save and page reload.
- Mobile Admin navigation includes Personalization and reflects the active tab.
- Generator remains usable on desktop and mobile after branding changes.

The Tailwind browser-build warning and missing Lucide source-map warning are known pre-existing console noise. A `Script terminated by timeout` message is not expected.
