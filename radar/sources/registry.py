"""Build Source objects from config/watchlist.yaml.

A source module registers a factory for its kind and is imported automatically:

    @register("greenhouse")
    def greenhouse(company, settings): return GreenhouseSource(company)

Kinds: a company's `ats` (greenhouse, lever, ...), "instagram", "github_repo",
and a feed's `kind` (rss, atom, ...).
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

import radar.sources
from radar.errors import ConfigError

log = logging.getLogger(__name__)
FACTORIES = {}  # kind -> factory(entry, settings) -> Source


def register(kind):
    def decorator(factory):
        FACTORIES[kind] = factory
        return factory
    return decorator


def _import_source_modules():
    for module in pkgutil.iter_modules(radar.sources.__path__):
        if module.name != "registry":
            importlib.import_module(f"radar.sources.{module.name}")


def build_sources(watchlist, settings=None):
    """Returns (sources, skipped kinds that have no registered factory yet)."""
    _import_source_modules()
    entries = (
        [(company.ats, company) for company in watchlist.companies]
        + [("instagram", account) for account in watchlist.instagram]
        + [(feed.kind, feed) for feed in watchlist.feeds]
        + [("github_repo", repo) for repo in watchlist.repos]
    )
    sources, skipped = [], set()
    for kind, entry in entries:
        factory = FACTORIES.get(kind)
        if factory is None:
            skipped.add(kind)
        else:
            sources.append(factory(entry, settings))
    names = [source.name for source in sources]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"watchlist yields duplicate source names: {duplicates}")
    if skipped:
        log.warning("no source registered for: %s", ", ".join(sorted(skipped)))
    return sources, sorted(skipped)


MAX_INSTAGRAM_ACCOUNTS = 5  # load_watchlist enforces this per file; the union needs it too


def build_sources_for_users(users, settings=None):
    """The Scheduler polls one de-duplicated union across every user's watchlist
    -- two users both listing Stripe's Greenhouse board must poll it once, not
    twice. Returns (sources, {user_id: frozenset(source_names)}, skipped kinds).
    """
    by_name, owned, skipped = {}, {}, set()
    for user in users:
        sources, s = build_sources(user.watchlist, settings)
        skipped |= set(s)
        owned[user.id] = frozenset(source.name for source in sources)
        for source in sources:
            existing = by_name.get(source.name)
            if existing is None or source.interval_s < existing.interval_s:
                by_name[source.name] = source
    instagram_names = {name for name in by_name if name.startswith("instagram.")}
    if len(instagram_names) > MAX_INSTAGRAM_ACCOUNTS:
        raise ConfigError(
            f"users.yaml watchlists together list {len(instagram_names)} instagram accounts "
            f"(one shared IG_SESSIONID supports at most {MAX_INSTAGRAM_ACCOUNTS}): {sorted(instagram_names)}"
        )
    return list(by_name.values()), owned, sorted(skipped)
