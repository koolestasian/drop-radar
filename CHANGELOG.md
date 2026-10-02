# Changelog

Versions follow the web app (`web/package.json`). Every merge to `main` adds an entry and a `vX.Y.Z` tag.

## 0.4.0 (2026-10-03)

- Compact rows: a toggle beside Filters on Feed and All jobs swaps the roomy cards for one-line rows (about 50px against about 160px) that keep Save and Apply. Remembered per browser. The column picker from the plan was skipped: rows are cards, not a table.
- Frontend only. 26 e2e tests; Lighthouse accessibility and best practices 100.

## 0.3.1 (2026-10-03)

- Account menu in the top right (profile icon): Settings and Sign out, one tap from any screen. Sign out is no longer at the bottom of Settings.

## 0.3.0 (2026-10-03)

- Work-model badge (Remote, Hybrid, On site) on cards and in the detail panel, read from the location and from tags in the title. "Hybrid Cloud Engineer" is not mislabelled. Most postings do not say, so most cards show none.
- First-run welcome sheet for a new user (drawer on phone, side sheet on desktop): what the radar watches, how to read a card, where to set roles and alerts. Shown once per user per browser.
- Sources screen opens with four plain-words numbers (next check, healthy, checked in the last hour, typical alert speed); rate-limited sources read "rate limited, retrying".
- Frontend only; no backend change. 22 e2e tests; Lighthouse accessibility and best practices 100.

## 0.2.1 (2026-10-03)

- No emoji anywhere live: push notifications no longer carry the briefcase tag (ntfy turned it into an emoji); text arrows in Settings and Sources are now drawn icons or plain words.

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
