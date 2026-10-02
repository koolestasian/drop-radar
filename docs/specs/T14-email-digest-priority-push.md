# T14: hourly email digest + phone push for the priority list

Retire GitHub Actions as the notification path (user, 2026-10-02):
- **Email, hourly:** new job drops since the last digest, sent to the user's email,
  only when there are some.
- **Phone push:** only for items on the user's priority list.

## Current state
- Owner: no working push. The legacy hourly job fails before its push step (see T13).
  The owner's ntfy topic is staged in `/opt/radar/alert-cutover.env` but not loaded into
  `radar.env`. Copying it needs the user's explicit yes (the classifier blocked it once).
- Friend: ntfy live (`NTFY_TOPIC_FRIEND`), 2 pushes sent; every profile match pushes.

## Ask once, up front (defaults in brackets)
1. What is the priority list? [zero2sudo Stories + companies tiered S/A, from the
   watchlist tier or `profile.company_tiers`, editable in Settings]
2. Email sender? [Gmail SMTP, `smtp.gmail.com:587`, with an app password the user
   creates in their Google account; check OCI allows outbound 587. Resend, Postmark and
   similar need a verified domain, and we only have nip.io.]
3. Should the friend get the digest too, and the same push rule?
4. Retire the hourly GitHub job entirely (it fails every hour and feeds the xlsx and
   Google Sheet), or fix Apify and keep it for the Sheet?

## Design (defaults)
- **Push:** add a priority gate to the one shared predicate (`should_alert` /
  `visible_to`), so the feed and the phone still agree on "what alerts this user".
  Keep claim-before-send.
- **Digest:** one hourly scheduler job per user.
  - Content: New (non-backfill) matches first seen since that user's last digest,
    grouped by company: title, location, posted-ago, link.
  - Send plain text plus a minimal HTML version, with stdlib `smtplib` +
    `email.message` (no new dependency).
  - Persist the digest window per user (a store key such as `digest:<user>`) and claim
    it before sending, so a restart neither resends nor skips a window. Send only
    after persistence.
- **Secrets:** `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` and `EMAIL_TO_<ID>` live in
  `radar.env` only. Never put addresses or passwords in committed files.
- **Then the cutover:**
  - load the owner's topic,
  - set GitHub's `LEGACY_ALERTS_ENABLED=false`,
  - drop hourly.yml's `schedule:` if question 4 says so.

## Acceptance
- Offline tests (fake SMTP and clock): the window advances once per send, a restart
  mid-window doesn't resend, no email when nothing is new, and the priority gate
  agrees between the feed and the push.
- Live: an email actually arrives in the user's inbox, and a test push shows on their
  phone after they subscribe from Settings (device receipt, not HTTP 200).
