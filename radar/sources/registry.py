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
