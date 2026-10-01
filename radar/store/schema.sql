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
    sent_at        TEXT,
    PRIMARY KEY (opportunity_id, channel)   -- one alert per channel, ever
);

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
