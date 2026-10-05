"""Read-only explanations: current gates are not historical rejection evidence."""
import json
from urllib.parse import urlparse

from radar.alerts import DEAD_STATUSES, should_alert, visible_to
from radar.api.models import DiagnosticCheck, LinkDiagnostic
from radar.pipeline.enrich import _regex_facts
from radar.pipeline.normalize import canonical_url
from radar.pipeline.pagefacts import _public, fetch_facts
from radar.models import Item
from radar.sources.ats import matches_title


def public_url(url):
    parts = urlparse(url)
    # Reading .port also rejects malformed port strings before requests sees them.
    port = parts.port
    return (parts.scheme in ("http", "https") and bool(parts.hostname) and parts.username is None
            and parts.password is None and (port is None or 0 < port <= 65535) and _public(parts.hostname))


def fetch_preview(url):
    return fetch_facts(url)


def source_of(url):
    """Only identify board URLs whose source name can be recovered exactly."""
    parts = urlparse(url)
    host, path = (parts.hostname or "").lower(), [p for p in parts.path.split("/") if p]
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io") and len(path) >= 3 and path[1] == "jobs":
        return f"ats.greenhouse.{path[0]}"
    if host == "jobs.lever.co" and len(path) >= 2:
        return f"ats.lever.{path[0]}"
    if host == "jobs.ashbyhq.com" and len(path) >= 2:
        return f"ats.ashby.{path[0]}"
    if host == "jobs.smartrecruiters.com" and len(path) >= 2:
        return f"ats.smartrecruiters.{path[0]}"
    if host.endswith(".myworkdayjobs.com"):
        if path and "-" in path[0] and len(path[0]) == 5:
            path = path[1:]
        if len(path) >= 3 and path[1] == "job":
            return f"ats.workday.{host.split('.myworkdayjobs.com')[0]}/{path[0]}"
    return None


def stored_link(store, url, owned, user_id):
    # Scope before URL matching, so another user's existence is never evidence.
    if not owned:
        return None
    marks = ",".join("?" for _ in owned)
    rows = store.conn.execute(
        f"""SELECT DISTINCT o.id, o.url, i.url AS item_url FROM opportunities o JOIN items i
            ON i.opportunity_id=o.id WHERE i.source IN ({marks}) ORDER BY o.first_seen DESC, o.id""", tuple(sorted(owned)))
    for row in rows:
        if canonical_url(row["url"]) == url or canonical_url(row["item_url"]) == url:
            return store.get_opportunity(row["id"], user_id=user_id)
    return None


def explain(url, user, owned, opp=None, facts=None, alerts=None):
    checks = []

    def add(stage, verdict, explanation, evidence=None):
        checks.append(DiagnosticCheck(stage=stage, verdict=verdict, explanation=explanation, facts=evidence or {}))

    known = opp is not None
    sources = sorted({i["source"] for i in opp["items"] if i["source"] in owned}) if known else []
    facts = facts or {}
    source = facts.get("source") or source_of(url)
    if known:
        add("collection", "passed", "Collected by your sources.", {"sources": ", ".join(sources)})
    else:
        coverage = ("This board is watched; absence does not prove which gate rejected it." if source in owned else
                    "This board is not in your current watchlist." if source else "Source coverage could not be established.")
        add("collection", "unknown", "Not collected by your sources. " + coverage,
            {"source": source} if source else {})
        if facts.get("title"):
            item = Item(source=source or "diagnostic", external_id="preview", url=url, title=facts["title"],
                        text=facts["title"], company=facts.get("company", ""), location=facts.get("location", ""))
            extracted = _regex_facts(item)
            opp = {"title": item.title, "company": item.company, "location": item.location,
                   "status": "New", "fields": {k: extracted[k] for k in ("Category", "Role / Track", "Season / Year")
                                               if extracted.get(k)}, "deadline": facts.get("deadline", "")}
    title = opp["title"] if opp else ""
    ats_sources = [s for s in sources if s.startswith("ats.")] if known else ([source] if source and source.startswith("ats.") else [])
    # The shared early-career title filter applies to AtsSource boards, not all source plugins.
    supported = ("ats.greenhouse.", "ats.lever.", "ats.ashby.", "ats.smartrecruiters.", "ats.workday.")
    if title and any(s.startswith(supported) for s in ats_sources):
        ok = matches_title(title)
        add("title", "passed" if ok else "blocked", "Current ATS early-career title gate " + ("passes." if ok else "rejects this title."), {"title": title})
    else:
        add("title", "unknown", "The ATS title gate is not applicable or the title/source is unavailable.")
    if known:
        ok, reasons = visible_to(opp, user.profile, owned)[1:]
        add("profile", "passed" if ok else "blocked", "; ".join(reasons) or "Matches your current profile.")
    elif opp and source:
        ok, reasons = should_alert(source, opp, user.profile)
        add("profile", "passed" if ok else "blocked", "With the currently fetched facts: " + ("; ".join(reasons) or "matches your profile."))
    else:
        add("profile", "unknown", "Public posting facts or source identity are unavailable; profile eligibility is inconclusive.")
    if known:
        hidden = (opp.get("action") or {}).get("status") == "ignored"
        dead = opp["status"] in DEAD_STATUSES
        add("visibility", "blocked" if hidden or dead else "passed",
            "You hid this job." if hidden else f"Posting status: {opp['status']}." if dead else
            "Eligible for the default Jobs list if it matches your profile. Active Jobs filters may still hide it.",
            {"status": opp["status"], "deadline": opp.get("deadline") or ""})
        mine = [i for i in opp["items"] if i["source"] in owned]
        seed = all(json.loads(i["raw"] or "{}").get("seed") for i in mine)
        add("backfill", "blocked" if seed else "passed",
            "Recorded as already open when your sources first looked; backfill does not trigger a new-drop alert." if seed else
            "At least one of your sightings is recorded as a live drop.")
        if alerts:
            add("alerts", "passed" if any(a["sent_at"] for a in alerts) else "unknown",
                "An alert was recorded as sent; device receipt is not verified." if any(a["sent_at"] for a in alerts) else
                "An alert is recorded as pending.")
        else:
            add("alerts", "unknown", "No alert delivery record is available for your configured channels. Historical causes are not reconstructed.")
    else:
        for stage, message in (("visibility", "No stored posting status or hidden state is available."),
                               ("backfill", "No sighting history is available."),
                               ("alerts", "No alert history is available.")):
            add(stage, "unknown", message)
    return LinkDiagnostic(url=url, collected=known,
                          summary="Current rules and recorded evidence; these checks do not reconstruct past rejection decisions.",
                          checks=checks)
