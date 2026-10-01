"""normalize: canonical URL and canonical company name.

ponytail: reuses radar.legacy.opportunity_monitor's clean_url/display_org and
their ~400-name ORG_ALIASES/KNOWN_ORGS tables as-is instead of copying them
into a new config/orgs.yaml -- that would be a pure data move with no
behavior change and a real risk of the two drifting. Move it if/when
something other than this pipeline needs the list without importing legacy.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from radar.legacy import opportunity_monitor as legacy

# Community lists (T4, e.g. SimplifyJobs) link through Simplify's own tracking
# param; legacy.clean_url only strips utm_*/fbclid/gclid/igshid/mc_*.
_EXTRA_TRACKING_PARAMS = {"ref"}


def canonical_url(url: str) -> str:
    url = legacy.clean_url(url)
    if not url:
        return url
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if k.lower() not in _EXTRA_TRACKING_PARAMS]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(query), ""))


def canonical_company(name: str) -> str:
    return legacy.display_org(name) if name else ""
