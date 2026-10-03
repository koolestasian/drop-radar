-- Drop Radar store. Idempotent: run on every connect. Add `PRAGMA user_version`
-- migrations the first time an existing table has to change.

CREATE TABLE IF NOT EXISTS opportunities (
    id           TEXT PRIMARY KEY,          -- permanent; legacy tracker IDs are kept
    title        TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',  -- canonical apply link when known
    company      TEXT NOT NULL DEFAULT '',
    location     TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'New',
    deadline     TEXT NOT NULL DEFAULT '',
    first_seen   TEXT NOT NULL,             -- ISO UTC; earliest sighting across items
    published_at TEXT,                      -- ISO UTC; earliest source publish time
    fields       TEXT NOT NULL DEFAULT '{}' -- JSON: other tracker columns (Category, Raw Text, ...)
);

CREATE TABLE IF NOT EXISTS items (
    source         TEXT NOT NULL,
    external_id    TEXT NOT NULL,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    url            TEXT NOT NULL DEFAULT '',
    title          TEXT NOT NULL DEFAULT '',
    published_at   TEXT,
    seen_at        TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL,
    raw            TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (source, external_id)
);
CREATE INDEX IF NOT EXISTS items_opportunity ON items(opportunity_id);

CREATE TABLE IF NOT EXISTS source_state (
    name       TEXT PRIMARY KEY,
    etag       TEXT,
    cursor     TEXT,
    last_ok    TEXT,
    fail_count INTEGER NOT NULL DEFAULT 0,
    next_run   TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    channel        TEXT NOT NULL,
    sent_at        TEXT,                    -- NULL = claimed but not yet sent (pending, safe to retry)
    PRIMARY KEY (opportunity_id, channel)   -- one alert per channel, ever
    -- drop_latency_s REAL added by MIGRATIONS[1] (T7), like source_state.last_error above
);

-- MIGRATIONS[2] (T8a) rebuilds this with user_id and PRIMARY KEY (opportunity_id, user_id).
CREATE TABLE IF NOT EXISTS actions (
    opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(id),
    status         TEXT NOT NULL DEFAULT '',
    notes          TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enrichment (
    key  TEXT PRIMARY KEY,   -- "page:<url>" or "llm:<text hash>"
    json TEXT NOT NULL
);

-- Accounts people create themselves (users.yaml users are not here). The id is generated and never reused:
-- statuses, notes and alerts are filed under it, so a freed username can't inherit someone's notes.
CREATE TABLE IF NOT EXISTS accounts (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    profile    TEXT NOT NULL DEFAULT '{}',   -- JSON, same shape as profile.yaml
    watchlist  TEXT NOT NULL DEFAULT '{}'    -- JSON: this account's extra companies, on top of the shared set
);

-- How someone signs in: any user (a users.yaml user or an account) can have one username and password.
CREATE TABLE IF NOT EXISTS credentials (
    username   TEXT PRIMARY KEY,             -- lower-case
    user_id    TEXT NOT NULL UNIQUE,
    pw_hash    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Login sessions: only the SHA-256 of the token is stored, so the table can't be replayed.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
