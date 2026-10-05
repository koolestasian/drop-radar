"""Explicit hide feedback: suggest, never silently change a profile."""
import dataclasses
from datetime import timedelta

from radar.alerts import DEAD_STATUSES, visible_to
from radar.api.models import ProfileSuggestions, Suggestion
from radar.pipeline.filter import excluded_term


def normalize_term(term):
    return " ".join(term.lower().split())


def suggestions(store, user, owned, now):
    muted = [r[0] for r in store.conn.execute(
        "SELECT term FROM muted_profile_terms WHERE user_id=? ORDER BY term", (user.id,))]
    rows = store.conn.execute(
        """SELECT a.hide_term, o.title FROM actions a JOIN opportunities o ON o.id=a.opportunity_id
           WHERE a.user_id=? AND a.status='ignored' AND a.hide_term IS NOT NULL
           AND julianday(a.hide_term_at) >= julianday(?) ORDER BY a.hide_term, a.hide_term_at DESC""",
        (user.id, (now - timedelta(days=30)).isoformat()))
    support = {}
    for term, title in rows:
        support.setdefault(term, []).append(title)
    excluded = {normalize_term(t) for t in user.profile.exclude}
    candidates = {term: titles for term, titles in support.items()
                  if len(titles) >= 3 and term not in excluded and term not in muted}
    result = []
    # Only do the source-scoped scan when feedback has reached the threshold.
    profiles = {term: dataclasses.replace(user.profile, exclude=(*user.profile.exclude, term)) for term in candidates}
    counts, examples = dict.fromkeys(candidates, 0), {term: [] for term in candidates}
    if candidates:
        seen = set()
        for row in store.iter_opportunities(source_names=owned):
            # Match Jobs/summary: choose the newest twin before hidden/dead/profile gates.
            twin = (row["company"].lower(), row["title"].lower().strip(), row["location"].lower().strip())
            if twin in seen:
                continue
            seen.add(twin)
            if not excluded_term(row["title"], candidates):
                continue
            opp = store.get_opportunity(row["id"], user_id=user.id)
            if opp["status"] in DEAD_STATUSES or (opp["action"] or {}).get("status") == "ignored":
                continue
            if not visible_to(opp, user.profile, owned)[1]:
                continue
            for term, profile in profiles.items():
                if not visible_to(opp, profile, owned)[1]:
                    counts[term] += 1
                    if len(examples[term]) < 3:
                        examples[term].append(opp["title"])
    for term, titles in candidates.items():
        result.append(Suggestion(term=term, support_count=len(titles), supporting_titles=titles[:3],
                                 affected_count=counts[term], examples=examples[term]))
    return ProfileSuggestions(suggestions=result, muted=muted)


def validate_feedback(term, title):
    term = normalize_term(term)
    if not term or not excluded_term(title, (term,)):
        raise ValueError("Choose a word or phrase that matches this job's title.")
    return term
