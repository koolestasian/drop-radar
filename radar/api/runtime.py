"""Runtime: the one Scheduler + Pipeline this process runs for every configured user.

reload() re-reads config/users.yaml and each user's watchlist/profile and swaps
them in place -- that is the whole hot-reload mechanism for watchlist, profile
and user edits. Everything is built and validated before anything running is
touched, so a bad edit raises and leaves the old config live.
"""
from __future__ import annotations

import os

from radar.alerts import AlertDispatcher, MultiUserAlertDispatcher, channels_for
from radar.api.events import EventBus
from radar.config import load_settings, load_users
from radar.errors import ConfigError
from radar.pipeline import Pipeline
from radar.pipeline.normalize import canonical_url
from radar.scheduler import Scheduler
from radar.sources.registry import build_sources_for_users

OWNER_KEY = "meta:owner"  # kept in the enrichment table, the store's generic key -> json


def claim_owner(store, users):
    """users.yaml can't silently drop a user who has saved statuses, or reorder who
    is first: the first user owns the "ntfy" channel and its alert history, so a
    swap would re-send every alert the old owner already got."""
    ids = {u.id for u in users}
    orphaned = sorted(row[0] for row in store.conn.execute("SELECT DISTINCT user_id FROM actions")
                      if row[0] not in ids)
    if orphaned:
        raise ConfigError(f"users.yaml has no user {orphaned}, but their saved statuses/notes are in the "
                          f"store; renaming or removing a user orphans them -- put them back")
    owner = store.get_enrichment(OWNER_KEY)
    if owner is None:
        store.set_enrichment(OWNER_KEY, users[0].id)
    elif owner != users[0].id:
        raise ConfigError(f"users.yaml's first user is {users[0].id!r}, but was {owner!r}: the first user "
                          f"owns the original alert channel and its history -- put {owner!r} back first")


class Runtime:
    def __init__(self, store, settings=None, users_path=None, env=None, channels_for=channels_for):
        self.store = store
        self.channels_for = channels_for
        self.settings = settings or load_settings()
        self.users_path = users_path
        self.env = os.environ if env is None else env
        self.scheduler = self.pipeline = None
        self.events = EventBus()
        store.recanonicalize_urls(canonical_url)  # rows from before a canonical_url rule change
        self.reload()

    def reload(self):
        users = load_users(self.users_path)
        claim_owner(self.store, users)
        sources, owned, _skipped = build_sources_for_users(users, self.settings)
        # Keep each user's AlertDispatcher across reloads: its in-flight/backoff memory is
        # what stops a send already under way from being sent again by the next retry sweep.
        previous = self.pipeline.alerter.dispatchers if self.pipeline is not None else {}
        dispatchers, profiles = {}, {}
        for i, user in enumerate(users):
            channels = self.channels_for(user.id, i == 0, self.env)
            old = previous.get(user.id)
            if old is not None and [c.name for c in old.channels] == [c.name for c in channels]:
                dispatchers[user.id], profiles[user.id] = old, user.profile  # profile applied once all is valid
            else:
                dispatchers[user.id] = AlertDispatcher(self.store, profile=user.profile, channels=channels)
        alerter = MultiUserAlertDispatcher(dispatchers, owned)
        if self.scheduler is None:
            self.pipeline = Pipeline(self.store, alerter=alerter)
            self.pipeline.on_new = lambda opportunity_id: self.events.publish("opportunity", opportunity_id)
            self.scheduler = Scheduler(sources, self.store, sink=self.pipeline,
                                       heartbeat_url=self.settings.heartbeat_url)
        else:
            self.scheduler.reload(sources)
            self.pipeline.alerter = alerter
        for user_id, profile in profiles.items():
            dispatchers[user_id].profile = profile
        self.users = {u.id: u for u in users}
        self.owned = owned
