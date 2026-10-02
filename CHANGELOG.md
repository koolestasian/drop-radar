# Changelog

Versions follow the web app (`web/package.json`). Every merge to `main` adds an entry and a `vX.Y.Z` tag.

## 0.2.0 (2026-10-03)

Web redesign, deployed to the live box 2026-10-02 20:43 UTC.

- Index-card board on shadcn (Radix) and Tailwind v4: card colour is the state, always with a text label; dark mode follows the device.
- Feed groups repeated roles into one row and has track chips with counts.
- Role detail: pane on desktop, drawer on phone. Filters sheet, labelled phone tab bar, 44px touch targets.
- Board, Settings and Sources restyled; those screens load lazily.
- Fixes from a DevTools pass: drawer focus, input name, mobile-web-app-capable. Lighthouse mobile: accessibility 100, best practices 100.
- No backend changes.

## 0.1.0 (2026-10-02)

Drop Radar service: pipeline, scheduler, API, PWA, live on Oracle Cloud. The hourly GitHub Actions job is retired (tag `legacy-hourly-monitor`).
