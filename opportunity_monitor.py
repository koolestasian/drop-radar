#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

import requests
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image
import pytesseract

import instagram_scraper
import job_pages

try:  # Some Story media is HEIC, which Pillow cannot open on its own.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

USERNAME = os.getenv("IG_USERNAME", "zero2sudo").lstrip("@")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
TRACKER_PATH = Path(os.getenv("TRACKER_PATH", "Zero2Sudo_Opportunity_Tracker.xlsx"))
STATUS_PATH = Path(os.getenv("STATUS_PATH", "monitor_status.json"))
STATE_PATH = Path(os.getenv("STATE_PATH", "monitor_state.json"))
LIVE_VIEW_PATH = Path(os.getenv("LIVE_VIEW_PATH", "LATEST.md"))

ENRICHMENT_PATH = Path(os.getenv("ENRICHMENT_PATH", "enrichment_cache.json"))

# "auto": native scraper first, Apify as fallback; "native" or "apify" force one.
SCRAPER = os.getenv("SCRAPER", "auto").strip().lower() or "auto"
IG_SESSIONID = os.getenv("IG_SESSIONID", "").strip()
POST_LOOKBACK_DAYS = int(os.getenv("POST_LOOKBACK_DAYS", "3"))

JOB_PAGES_ENABLED = os.getenv("JOB_PAGES", "on").strip().lower() not in {"0", "off", "false", "no"}
PAGE_CHECKS_PER_RUN = int(os.getenv("PAGE_CHECKS_PER_RUN", "80"))
PAGE_RECHECK_HOURS = int(os.getenv("PAGE_RECHECK_HOURS", "24"))
LLM_ENABLED = bool(
    os.getenv("ANTHROPIC_API_KEY", "").strip() or os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
) and os.getenv("LLM_EXTRACTION", "on").strip().lower() not in {"0", "off", "false", "no"}
LLM_BACKFILL_PER_RUN = int(os.getenv("LLM_BACKFILL_PER_RUN", "25"))
LLM_DROP_CONFIDENCE = float(os.getenv("LLM_DROP_CONFIDENCE", "0.8"))

STORY_ACTOR = os.getenv("STORY_ACTOR", "data-slayer/instagram-stories-scraper")
POST_ACTOR = os.getenv("POST_ACTOR", "apify/instagram-scraper")

GITHUB_TOKEN = os.getenv("GH_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").strip() or "https://ntfy.sh"
NTFY_TOKEN = os.getenv("NTFY_TOKEN", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SYNC_REQUIRED = os.getenv("GOOGLE_SYNC_REQUIRED", "false").strip().lower() in {
    "1", "true", "yes"
}

REQUEST_TIMEOUT = 180

HEADERS = [
    "ID", "First Seen", "Posted At", "Organization", "Opportunity", "Category",
    "Role / Track", "Season / Year", "Location", "Deadline",
    "Application / Registration Link", "Instagram Source", "Source Type",
    "Raw Text", "Status", "Priority", "Actioned?", "Notes"
]

OPPORTUNITY_RE = re.compile(
    r"\b("
    r"intern(ship)?|new grad|early career|entry[- ]level|hiring|job opening|open role|student job|"
    r"fellowship|scholarship|grant|stipend|hackathon|conference|summit|career fair|"
    r"recruiting event|networking event|meetup|workshop|webinar|info session|information session|"
    r"office hours|coffee chat|resume review|mentorship|mentor program|cohort|ambassador program|"
    r"campus program|student program|university program|research opportunity|research program|"
    r"apprenticeship|externship|competition|challenge|accelerator|incubator|pitch competition|"
    r"direct consideration|referral|early talent|talent network|talent community|"
    r"applications? (?:are )?(?:open|opened|reopened|live)|apps? (?:are )?(?:open|opened|reopened|live)|"
    r"apply now|register now|registration (?:is )?open|rsvp|sign[- ]?up|submit|deadline|"
    r"join us|apply here|register here|opportunity"
    r")\b",
    re.I,
)

ACTION_RE = re.compile(
    r"\b(apply|register|rsvp|sign[- ]?up|submit|join|nominate|deadline|applications?|registration)\b",
    re.I,
)

NOISE_RE = re.compile(
    r"\b(resume tips?|interview tips?|leetcode tips?|career advice|motivation|day in the life|"
    r"salary transparency|story time|q&a|ama)\b",
    re.I,
)

NEGATIVE_CONTEXT_RE = re.compile(
    r"\b(got|received|accepted|landed)\s+(?:an?\s+)?(?:intern(?:ship)?\s+)?offer\b|"
    r"\boffer\s*[+&/]?\s*process\b|\bhas anyone\b|\bdid anyone\b|"
    r"\bno sign[- ]?up\b|\bno registration\b|\bhiring happens\b|"
    r"\bapplication process\b|\binterview process\b|\brecap\b|"
    r"\bthis is why\b|\bwhat are my chances\b",
    re.I,
)

STRONG_ACTION_RE = re.compile(
    r"\b(apply now|apply here|applications? (?:are )?(?:open|live)|"
    r"registration (?:is )?open|register now|register here|rsvp|"
    r"sign[- ]?up|deadline|apply by|register by|submissions? (?:are )?open)\b",
    re.I,
)

ROLE_PATTERNS = [
    ("Software Engineering", r"\b(?:swe|software engineer(?:ing)?)\b"),
    ("Product Management", r"\b(?:pm|product manager|product management)\b"),
    ("Technical Program Management", r"\b(?:tpm|technical program manager|technical program management)\b"),
    ("Machine Learning / AI", r"\b(?:machine learning|ml intern|ai intern|artificial intelligence|genai)\b"),
    ("Data Science", r"\b(?:data scientist|data science)\b"),
    ("Data Engineering", r"\b(?:data engineer|data engineering)\b"),
    ("Quant", r"\b(?:quant|quantitative researcher|quantitative trader|quantitative developer)\b"),
    ("Research", r"\b(?:research intern|research scientist|researcher)\b"),
    ("Design", r"\b(?:product design|ux design|ui design|designer intern)\b"),
    ("Hardware", r"\b(?:hardware engineer|hardware engineering)\b"),
    ("Business / Operations", r"\b(?:business operations|bizops|operations intern)\b"),
]

KNOWN_ORGS = [
    "Microsoft", "Amazon", "Google", "Meta", "Apple", "NVIDIA", "Palantir", "Anduril",
    "Figma", "Notion", "Adobe", "Uber", "Stripe", "Databricks", "Snowflake", "Salesforce",
    "Coinbase", "Roblox", "Airbnb", "DoorDash", "Capital One", "Citadel",
    "Citadel Securities", "Optiver", "IMC Trading", "Jane Street", "D. E. Shaw",
    "Hudson River Trading", "Two Sigma", "LinkedIn", "MongoDB", "Cloudflare",
    "Atlassian", "Asana", "Dropbox", "Pinterest", "Reddit", "Snap", "TikTok", "ByteDance",
    "OpenAI", "Anthropic", "Scale AI", "Shield AI", "Vannevar Labs", "Primer",
    "Tesla", "SpaceX", "Waymo", "Lyft", "Shopify", "Spotify", "Netflix", "Rippling",
    "Ramp", "Vercel", "Cerebras", "Perplexity", "Quora", "Robinhood", "Plaid", "Intuit",
    "Visa", "Cisco", "AMD", "Intel", "IBM", "Qualcomm", "Oracle", "Verizon", "AT&T",
    "T-Mobile", "Walmart", "Target", "Disney", "Bloomberg", "Point72",
    "Tower Research Capital", "Geneva Trading", "CME Group", "Jump Trading", "SIG",
    "Goldman Sachs", "Morgan Stanley", "JPMorgan Chase", "BlackRock", "Barclays",
    "Fidelity", "Liberty Mutual", "State Farm", "Wells Fargo", "Bank of America",
    "Macquarie", "PwC", "Deloitte", "Accenture", "Boeing", "Lockheed Martin",
    "Northrop Grumman", "Garmin", "Rivian", "Zipline", "SeatGeek", "Rubrik", "Epic Games",
    "EA", "Riot Games", "Duolingo", "Datadog", "Twilio", "Workday", "ServiceNow",
    "PayPal", "Together AI", "ZipRecruiter", "Under Armour", "GE HealthCare", "Cigna",
    "Boston Scientific", "H&R Block", "First Citizens", "NASA", "Box",
    "Klaviyo", "Astranis", "Mercury", "Figure", "Samsara", "Nuro", "Aurora",
]

# Slugs that do not normalize onto a KNOWN_ORGS name by themselves.
ORG_ALIASES = {
    "withwaymo": "Waymo",
    "doordashusa": "DoorDash",
    "optiverprivate": "Optiver",
    "scaleai": "Scale AI",
    "togetherai": "Together AI",
    "cmegroup": "CME Group",
    "genevatrading": "Geneva Trading",
    "headlandstechnologies": "Headlands Technologies",
    "queracomputing": "QuEra Computing",
    "thecignagroup": "Cigna",
    "gehealthcare": "GE HealthCare",
    "underarmour": "Under Armour",
    "statefarm": "State Farm",
    "capitalone": "Capital One",
    "bostonscientific": "Boston Scientific",
    "libertymutual": "Liberty Mutual",
    "firstcitizens": "First Citizens",
    "hrblock": "H&R Block",
    "lifeatspotify": "Spotify",
    "metacareers": "Meta",
    "epicgames": "Epic Games",
    "towerresearch": "Tower Research Capital",
    "arcteryx": "Arc'teryx",
    "arcteryxcom": "Arc'teryx",
    "att": "AT&T",
    "fmr": "Fidelity",
    "jpmc": "JPMorgan Chase",
    "jpmorgan": "JPMorgan Chase",
    "q2ebanking": "Q2",
    "erac": "Enterprise Mobility",
    "enterprisemobility": "Enterprise Mobility",
    "ea": "EA",
    "sig": "SIG",
    "nfa": "NFA",
    "icf": "ICF",
    "amd": "AMD",
    "vannevar": "Vannevar Labs",
    "shieldai": "Shield AI",
    "hrt": "Hudson River Trading",
    "deshaw": "D. E. Shaw",
    "janestreet": "Jane Street",
    "twosigma": "Two Sigma",
    "wurljobs": "Wurl",
    "voyagertechnologies": "Voyager Technologies",
    "metoxinternational": "Metox International",
    "assuredguaranty": "Assured Guaranty",
    "headlands": "Headlands Technologies",
    "tylertech": "Tyler Technologies",
    "linkedin3": "LinkedIn",
    "financialtimes": "Financial Times",
    "bcbsm": "Blue Cross Blue Shield of Michigan",
    "ulsolutions": "UL Solutions",
    "gunvor": "Gunvor",
    "wabashvalleypoweralliance": "Wabash Valley Power Alliance",
    "prizepicks": "PrizePicks",
    "rizepicks": "PrizePicks",
    "redventures": "Red Ventures",
    "smartscholarship": "SMART Scholarship",
}

# Company-name suffixes that job-board slugs append to the real name.
ORG_SLUG_SUFFIXES = (
    "inc", "llc", "corp", "careers", "career", "campus", "jobs", "private",
    "group", "usa", "us", "global", "external",
)
ORG_SLUG_PREFIXES = ("the", "with", "lifeat", "join", "careers", "campus", "uscareers", "us", "jobs")

# Hosts whose name says nothing about the employer: shorteners, form and event
# tools, aggregators, and ATS domains that encode no company in the URL.
GENERIC_LINK_HOSTS = (
    "tinyurl.com", "bit.ly", "linktr.ee", "lu.ma", "luma.com", "forms.gle",
    "docs.google.com", "share.google", "forms.cloud.microsoft", "forms.office.com",
    "typeform.com", "eventbrite.com", "splashthat.com", "gem.com", "notion.site",
    "t.co", "rebrand.ly", "calendly.com", "youtube.com", "youtu.be",
    "directconsideration.com", "irectconsideration.com", "demystifyd.com",
    "oraclecloud.com", "ultipro.com", "brassring.com", "tal.net",
    "app.eightfold.ai", "app3.greenhouse.io", "app.greenhouse.io", "joinhandshake.com",
    "handshake.com", "wellfound.com", "indeed.com", "glassdoor.com", "simplify.jobs",
)

# ATS hosts where the company is the first path segment.
ATS_PATH_HOSTS = {
    "jobs.lever.co", "boards.greenhouse.io", "job-boards.greenhouse.io",
    "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io", "jobs.ashbyhq.com",
    "jobs.smartrecruiters.com", "jobs.jobvite.com", "apply.workable.com",
    "ats.rippling.com", "jobs.gem.com",
}

# ATS domains where the company is the leftmost subdomain.
ATS_SUBDOMAIN_SUFFIXES = (
    "myworkdayjobs.com", "eightfold.ai", "icims.com", "avature.net",
    "jibeapply.com", "wd1.myworkdaysite.com", "recruitee.com", "bamboohr.com",
    "breezy.hr", "teamtailor.com", "pinpointhq.com",
)

DEFAULT_HIGH_PRIORITY_ORGS = [
    "Palantir", "Anduril", "Scale AI", "Primer", "Vannevar Labs", "Shield AI",
    "OpenAI", "Anthropic", "Databricks",
]
HIGH_PRIORITY_ORGS = [
    name.strip()
    for name in (os.getenv("HIGH_PRIORITY_ORGS") or ",".join(DEFAULT_HIGH_PRIORITY_ORGS)).split(",")
    if name.strip()
]

DOMAIN_ORGS = {
    "microsoft.com": "Microsoft",
    "amazon.jobs": "Amazon",
    "amazon.com": "Amazon",
    "google.com": "Google",
    "meta.com": "Meta",
    "apple.com": "Apple",
    "nvidia.com": "NVIDIA",
    "palantir.com": "Palantir",
    "anduril.com": "Anduril",
    "figma.com": "Figma",
    "notion.com": "Notion",
    "notion.so": "Notion",
    "adobe.com": "Adobe",
    "uber.com": "Uber",
    "stripe.com": "Stripe",
    "databricks.com": "Databricks",
    "snowflake.com": "Snowflake",
    "salesforce.com": "Salesforce",
    "coinbase.com": "Coinbase",
    "roblox.com": "Roblox",
    "airbnb.com": "Airbnb",
    "doordash.com": "DoorDash",
    "capitalone.com": "Capital One",
    "capitalonecareers.com": "Capital One",
    "citadel.com": "Citadel",
    "citadelsecurities.com": "Citadel Securities",
    "optiver.com": "Optiver",
    "imc.com": "IMC Trading",
    "janestreet.com": "Jane Street",
    "deshaw.com": "D. E. Shaw",
    "hudsonrivertrading.com": "Hudson River Trading",
    "twosigma.com": "Two Sigma",
    "linkedin.com": "LinkedIn",
    "mongodb.com": "MongoDB",
    "cloudflare.com": "Cloudflare",
    "atlassian.com": "Atlassian",
    "asana.com": "Asana",
    "dropbox.com": "Dropbox",
    "pinterest.com": "Pinterest",
    "redditinc.com": "Reddit",
    "snap.com": "Snap",
    "tiktok.com": "TikTok",
    "bytedance.com": "ByteDance",
}

def actor_url(actor_id):
    return f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"

def run_actor(actor_id, payload):
    # The token goes in a header, not the query string, so it never appears in
    # an exception message or log line that includes the request URL.
    response = requests.post(
        actor_url(actor_id),
        params={"timeout": REQUEST_TIMEOUT},
        headers={"Authorization": f"Bearer {APIFY_TOKEN}"},
        json=payload,
        timeout=REQUEST_TIMEOUT + 30,
    )
    if response.status_code >= 400:
        hint = {
            401: "APIFY_TOKEN is invalid or revoked",
            402: "the Apify account is out of credit",
            403: "the Apify token lacks permission for this actor",
            404: "the actor was not found; check STORY_ACTOR / POST_ACTOR",
        }.get(response.status_code, "Apify returned an error")
        raise RuntimeError(f"Actor {actor_id} failed with HTTP {response.status_code}: {hint}.")
    data = response.json()
    if not isinstance(data, list):
        shape = type(data).__name__
        keys = sorted(data)[:8] if isinstance(data, dict) else []
        raise RuntimeError(
            f"Actor {actor_id} returned unexpected {shape} payload"
            + (f" with keys {keys}" if keys else "")
        )
    if any(not isinstance(item, dict) for item in data):
        raise RuntimeError(f"Actor {actor_id} returned a non-object dataset item.")
    return data

SCRAPE_REPORT = {"scrapers": {}, "warnings": []}
ENRICHMENT_REPORT = {"pages_checked": 0, "postings_closed": 0, "filtered_by_llm": 0}
_native_client = None

def native_client():
    global _native_client
    if _native_client is None:
        _native_client = instagram_scraper.InstagramClient(IG_SESSIONID)
    return _native_client

def apify_stories():
    return run_actor(STORY_ACTOR, {"usernames": [USERNAME]})

def apify_posts():
    payload = {
        "directUrls": [f"https://www.instagram.com/{USERNAME}/"],
        "resultsType": "posts",
        "resultsLimit": 10,
        "onlyPostsNewerThan": f"{POST_LOOKBACK_DAYS} days",
        "skipPinnedPosts": True,
    }
    return run_actor(POST_ACTOR, payload)

def scrape(kind, native, apify):
    """Run the native scraper, falling back to Apify, per SCRAPER.

    A fallback is logged as a warning (it usually means IG_SESSIONID expired)
    rather than failing the check, because a missed Story is gone for good.
    """
    errors = []
    native_possible = kind != "Stories" or bool(IG_SESSIONID)
    if SCRAPER in {"auto", "native"} and (native_possible or SCRAPER == "native"):
        try:
            items = native()
            SCRAPE_REPORT["scrapers"][kind] = "native"
            return items
        except instagram_scraper.InstagramError as exc:
            errors.append(f"native: {exc}")
    if SCRAPER in {"auto", "apify"} and APIFY_TOKEN:
        try:
            items = apify()
            SCRAPE_REPORT["scrapers"][kind] = "apify (fallback)" if errors else "apify"
            for error in errors:
                warning = f"{kind}: {error}; used Apify instead."
                SCRAPE_REPORT["warnings"].append(warning)
                print(f"::warning::{warning}")
            return items
        except Exception as exc:
            errors.append(f"apify: {exc}")
    if not errors:
        errors.append(
            "no scraper is configured (set IG_SESSIONID for the native scraper and/or APIFY_TOKEN)"
        )
    raise RuntimeError(f"{kind} scrape failed; this check is incomplete. " + " | ".join(errors))

def fetch_stories():
    return scrape("Stories", lambda: native_client().stories(USERNAME), apify_stories)

def fetch_posts():
    return scrape(
        "Posts",
        lambda: native_client().recent_posts(USERNAME, POST_LOOKBACK_DAYS),
        apify_posts,
    )

def pick(item, *keys):
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return None

def as_text(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(map(str, value))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)

URL_RE = re.compile(r"https?://[^\s<>\"']+")
URL_TRAILING_PUNCTUATION = ".,;:!?)]}"

def _walk_urls(value):
    """Recursively collect URLs from arbitrary actor output.

    Story actors often put link-sticker/swipe-up URLs several levels deep,
    and their field names can change. Walking the whole object is more robust
    than depending on a short list of keys.
    """
    found = []
    if isinstance(value, str):
        found.extend(match.rstrip(URL_TRAILING_PUNCTUATION) for match in URL_RE.findall(value))
    elif isinstance(value, dict):
        for nested in value.values():
            found.extend(_walk_urls(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.extend(_walk_urls(nested))
    return found

def normalize_links(item):
    return list(dict.fromkeys(_walk_urls(item)))

def is_instagram_url(url):
    try:
        host = urlparse(url).netloc.lower()
        return host == "instagram.com" or host.endswith(".instagram.com") or host == "instagr.am"
    except Exception:
        return False

def is_media_url(url):
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        media_hosts = ("cdninstagram.com", "fbcdn.net", "scontent.", "cdn.fbsbx.com")
        media_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".mp4", ".m3u8", ".mov")
        return any(x in host for x in media_hosts) or path.endswith(media_exts)
    except Exception:
        return False

def unwrap_instagram_redirect(url):
    """Unwrap l.instagram.com redirects when a story actor returns them."""
    try:
        parsed = urlparse(url)
        if parsed.netloc.lower() in {"l.instagram.com", "l.facebook.com"}:
            params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            for key in ("u", "url", "href"):
                if params.get(key):
                    return params[key]
    except Exception:
        pass
    return url

def external_links(links):
    cleaned = []
    for raw in links:
        url = unwrap_instagram_redirect(raw)
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            valid = (
                parsed.scheme.lower() in {"http", "https"}
                and re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", host.lower()) is not None
            )
        except Exception:
            valid = False
        if valid and not is_instagram_url(url) and not is_media_url(url):
            cleaned.append(clean_url(url))
    return list(dict.fromkeys(cleaned))

def clean_url(url):
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        drop_prefixes = ("utm_",)
        drop_exact = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid"}
        query = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in drop_exact and not any(k.lower().startswith(p) for p in drop_prefixes)
        ]
        return urlunparse((
            parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"),
            "", urlencode(query), ""
        ))
    except Exception:
        return url

def image_url(item):
    value = pick(
        item, "image_url", "displayUrl", "display_url", "thumbnailUrl",
        "thumbnail_url", "imageUrl", "image", "media_url"
    )
    if isinstance(value, list):
        return value[0] if value else ""
    return value if isinstance(value, str) else ""

def ocr_image(url):
    if not url:
        return ""
    try:
        response = requests.get(url, timeout=45)
        response.raise_for_status()
        suffix = ".png" if "png" in response.headers.get("content-type", "").lower() else ".jpg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as temp:
            temp.write(response.content)
            temp.flush()
            # Grayscale gives Tesseract cleaner glyph edges on colorful Story art.
            image = Image.open(temp.name).convert("L")
            if image.width < 1400:
                scale = 1400 / max(image.width, 1)
                image = image.resize((int(image.width * scale), int(image.height * scale)))
            return pytesseract.image_to_string(image).strip()
    except Exception as exc:
        print(f"::warning::OCR failed: {exc}")
        return ""

def item_text(item):
    parts = [
        as_text(pick(item, "caption", "text", "title", "description")),
        as_text(pick(item, "hashtags")),
        as_text(pick(item, "mentions")),
    ]
    media = image_url(item)
    if media:
        parts.append(ocr_image(media))
    parts.extend(normalize_links(item))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(x.strip() for x in parts if x and x.strip())).strip()

def looks_actionable(text, links):
    if not text:
        return False
    opportunity = bool(OPPORTUNITY_RE.search(text))
    external = bool(external_links(links))
    strong_action = bool(STRONG_ACTION_RE.search(text))
    if NEGATIVE_CONTEXT_RE.search(text) and not external:
        return False
    if NOISE_RE.search(text) and not external and not strong_action:
        return False
    if external:
        return opportunity or bool(ACTION_RE.search(text))
    return opportunity and strong_action

def org_key(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

ORG_BY_KEY = {org_key(name): name for name in KNOWN_ORGS}

def _pretty_org(value):
    value = re.sub(r"[-_]+", " ", value or "").strip()
    return " ".join(part.upper() if len(part) <= 3 else part.capitalize() for part in value.split())

def _slug_variants(key):
    """Yield a slug and the versions of it without common prefixes/suffixes."""
    seen = []
    pending = [key]
    while pending:
        current = pending.pop(0)
        if not current or current in seen:
            continue
        seen.append(current)
        if current[-1:].isdigit():
            pending.append(current.rstrip("0123456789"))  # LinkedIn3, financialtimes33
        for prefix in ORG_SLUG_PREFIXES:
            if current.startswith(prefix) and len(current) - len(prefix) >= 2:
                pending.append(current[len(prefix):])
        for suffix in ORG_SLUG_SUFFIXES:
            if current.endswith(suffix) and len(current) - len(suffix) >= 2:
                pending.append(current[:-len(suffix)])
    return seen

def canonical_org(raw):
    """Map a host label or path slug such as 'doordashusa' to 'DoorDash'."""
    raw = unquote(str(raw or "")).strip()
    key = org_key(raw)
    if not key:
        return ""
    variants = _slug_variants(key)
    for variant in variants:
        if variant in ORG_ALIASES:
            return ORG_ALIASES[variant]
        if variant in ORG_BY_KEY:
            return ORG_BY_KEY[variant]
    # Unknown company: drop job-board words and unambiguous corporate
    # suffixes (careers-barrios, gunvorgroup, LinkedIn3), then prettify.
    words = [word for word in re.split(r"[-_.\s]+", raw) if word]
    board_words = {"careers", "career", "campus", "uscareers", "us", "jobs", "join", "the", "external"}
    while len(words) > 1 and words[0].lower() in board_words:
        words = words[1:]
    while len(words) > 1 and words[-1].lower() in board_words | {"inc", "llc", "corp"}:
        words = words[:-1]
    readable = " ".join(words)
    if " " not in readable:
        readable = readable.rstrip("0123456789") or readable
        compact = readable.lower()
        for suffix in ("inc", "llc", "corp", "careers", "campus", "jobs", "private", "group"):
            if compact.endswith(suffix) and len(compact) - len(suffix) >= 3:
                readable = readable[:-len(suffix)]
                break
    if org_key(readable) in {"americas", "global", "emea", "apac", "na", "us", "usa", "intl"}:
        return ""
    return _pretty_org(readable)

def _host_matches(host, domain):
    return host == domain or host.endswith("." + domain)

def _registrable_label(labels):
    """Company label of a hostname: 'mycareer.verizon.com' -> 'verizon'."""
    if len(labels) < 2:
        return ""
    if len(labels) >= 3 and labels[-2] in {"co", "com", "ac", "org"} and len(labels[-1]) == 2:
        label = labels[-3]
    else:
        label = labels[-2]
    if label in {"jobs", "careers", "career", "apply", "join"} and len(labels[-1]) > 3:
        label = labels[-1]  # e.g. search.jobs.barclays
    return label

def organization_from_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    host = parsed.netloc.lower().removeprefix("www.")
    path_parts = [part for part in parsed.path.split("/") if part]
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    labels = host.split(".")

    for domain, organization in DOMAIN_ORGS.items():
        if _host_matches(host, domain):
            if domain == "linkedin.com" and path_parts[:1] and path_parts[0] in {
                "jobs", "posts", "feed", "in", "company", "events", "comm",
            }:
                return ""  # LinkedIn hosts other companies' postings.
            if domain == "google.com" and host != "google.com" and not host.endswith("careers.google.com"):
                if host.startswith("docs.") or host.startswith("forms."):
                    return ""
            return organization

    if host.endswith("oraclecloud.com") and "sites" in path_parts:
        index = path_parts.index("sites")
        site = path_parts[index + 1] if len(path_parts) > index + 1 else ""
        site = re.sub(r"(?:Student|Early|University|Campus)?Careers?$", "", site)
        if site and not re.fullmatch(r"CX(?:_\d+)?", site, re.I):
            return canonical_org(re.sub(r"(?<=[a-z])(?=[A-Z])", "-", site))
        return ""
    if any(_host_matches(host, generic) for generic in GENERIC_LINK_HOSTS):
        return ""

    if host in ATS_PATH_HOSTS:
        if path_parts[:1] == ["embed"] and query.get("for"):
            return canonical_org(query["for"])  # Greenhouse embedded board
        return canonical_org(path_parts[0]) if path_parts else ""
    if host == "app.careerpuck.com":
        return canonical_org(path_parts[1]) if len(path_parts) > 1 else ""
    if host.endswith("myworkdaysite.com") and "recruiting" in path_parts:
        index = path_parts.index("recruiting")
        return canonical_org(path_parts[index + 1]) if len(path_parts) > index + 1 else ""
    for suffix in ATS_SUBDOMAIN_SUFFIXES:
        if _host_matches(host, suffix):
            candidate = labels[0]
            if re.fullmatch(r"wd\d+|app|www|careers|jobs", candidate):
                return ""
            return canonical_org(candidate)

    return canonical_org(_registrable_label(labels))

def organization_from_links(links):
    for url in external_links(links):
        organization = organization_from_url(url)
        if organization:
            return organization
    return ""

def organization_from_text(text):
    """Earliest well-known company named in the text.

    Matching is case-sensitive (exact, Title or UPPER case) so ordinary words
    such as 'visa sponsorship' or 'target audience' are not read as companies.
    """
    best = None
    for org in KNOWN_ORGS:
        forms = {re.escape(org), re.escape(org.upper()), re.escape(org.title())}
        match = re.search(rf"(?<![\w&])(?:{'|'.join(forms)})(?![\w&])", text)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), org)
    return best[1] if best else ""

def extract_organization(text, links):
    return organization_from_links(links) or organization_from_text(text)

CATEGORIES = [
    ("Internship", r"intern(?:ship)?s?|co-?op"),
    ("New Grad / Early Career", r"new grad(?:uate)?|new college grad(?:uate)?|early career|entry[- ]level|university graduate"),
    ("Job / Hiring", r"hiring|job opening|open role|student job"),
    ("Fellowship", r"fellowship"),
    ("Scholarship / Grant", r"scholarship|grant|stipend"),
    ("Hackathon / Competition", r"hackathon|pitch competition|competition|case challenge|coding challenge"),
    ("Conference / Summit", r"conference|summit"),
    ("Recruiting / Career Event", r"career fair|recruiting event|direct consideration"),
    ("Networking", r"networking event|meetup|coffee chat"),
    ("Workshop / Info Session", r"workshop|webinar|info session|information session|office hours|resume review"),
    ("Mentorship / Cohort", r"mentorship|mentor program|cohort"),
    ("Student / Campus Program", r"ambassador program|campus program|student program|university program"),
    ("Research", r"research opportunity|research program|research intern"),
    ("Apprenticeship / Externship", r"apprenticeship|externship"),
    ("Accelerator / Incubator", r"accelerator|incubator"),
    ("Referral / Talent Network", r"referral|early talent|talent network|talent community"),
]

def extract_category(text):
    for label, pattern in CATEGORIES:
        if re.search(rf"\b(?:{pattern})\b", text, re.I):
            return label
    return "Other Opportunity"

def extract_roles(text):
    return ", ".join(
        label for label, pattern in ROLE_PATTERNS if re.search(pattern, text, re.I)
    )

def extract_season(text):
    matches = re.findall(r"\b(Summer|Fall|Autumn|Winter|Spring)\s+'?((?:20)?\d{2})\b", text, re.I)
    seasons = []
    for season, year in matches:
        year = f"20{year}" if len(year) == 2 else year
        if re.fullmatch(r"20(?:2[4-9]|3\d)", year):
            seasons.append(f"{season.title()} {year}")
    if seasons:
        return ", ".join(dict.fromkeys(seasons))
    years = re.findall(r"\b20(?:2[6-9]|3\d)\b", text)
    return ", ".join(dict.fromkeys(years))

LOCATION_PLACES = [
    "Seattle", "Kirkland", "Bellevue", "Redmond", "San Francisco", "Bay Area",
    "New York", "NYC", "Austin", "Boston", "Chicago", "Los Angeles", "Sunnyvale",
    "Mountain View", "Menlo Park", "Palo Alto", "San Jose", "San Diego", "Denver",
    "Atlanta", "Dallas", "Houston", "Miami", "Pittsburgh", "Philadelphia",
    "Washington, DC", "Washington DC", "Toronto", "Waterloo", "Vancouver", "Montreal",
    "London", "Dublin", "Remote", "Hybrid",
]
US_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|"
    "MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"
)
CITY_STATE_RE = re.compile(rf"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?),\s?({US_STATES})\b")
NOT_A_CITY = {"Summer", "Fall", "Winter", "Spring", "Apply", "Intern", "Internship", "Program", "Now"}

def extract_location(text):
    found = [place for place in LOCATION_PLACES if re.search(rf"\b{re.escape(place)}\b", text, re.I)]
    for city, state in CITY_STATE_RE.findall(text):
        if city.split()[0] not in NOT_A_CITY and not any(city in place for place in found):
            found.append(f"{city}, {state}")
    return ", ".join(dict.fromkeys(found))

MONTH_RE = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RE = (
    rf"(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+)?"
    rf"(?:{MONTH_RE}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+20\d{{2}})?"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH_RE}(?:,?\s+20\d{{2}})?"
    rf"|\d{{1,2}}/\d{{1,2}}(?:/(?:20)?\d{{2}})?"
    rf"|20\d{{2}}-\d{{2}}-\d{{2}})"
)
DEADLINE_TRIGGER_RE = (
    r"(?:deadline(?:\s+to\s+(?:apply|register))?|due|apply\s+(?:by|before)|"
    r"register\s+(?:by|before)|submit\s+(?:by|before)|rsvp\s+by|"
    r"applications?\s+(?:close|closes|closing|due|end|ends)|"
    r"registration\s+(?:closes|ends|deadline)|closes|closing\s+date|ends|before|until)"
)
DEADLINE_RE = re.compile(
    rf"\b{DEADLINE_TRIGGER_RE}\b(?:\s+is)?(?:\s+on)?\s*[:\-–]?\s*"
    rf"(?:[^\n]{{0,30}}?\bon\s+)?({DATE_RE})(?![\d/])",
    re.I,
)

def parse_deadline(value, reference=None):
    """Best-effort date for a deadline string; None when it cannot be read."""
    if not value:
        return None
    reference = reference or datetime.now(timezone.utc).date()
    text = str(value).strip().lower()
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    text = re.sub(r"^(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+", "", text)
    text = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", text)
    text = text.replace(".", "").replace(",", " ")
    text = re.sub(r"\bsept\b", "sep", text)
    text = " ".join(text.split())
    formats_with_year = ("%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y", "%m/%d/%y")
    formats_without_year = ("%B %d", "%b %d", "%d %B", "%d %b", "%m/%d")
    for fmt in formats_with_year:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    for fmt in formats_without_year:
        try:
            parsed = datetime.strptime(f"{text} {reference.year}", f"{fmt} %Y").date()
        except ValueError:
            continue
        # A yearless date well before the post refers to next year.
        if parsed < reference - timedelta(days=60):
            parsed = parsed.replace(year=parsed.year + 1)
        return parsed
    return None

def extract_deadline(text, reference=None):
    """Deadline as ISO date when it can be parsed, otherwise the raw phrase."""
    for match in DEADLINE_RE.finditer(text or ""):
        raw = " ".join(match.group(1).split()).strip(" ,.")
        parsed = parse_deadline(raw, reference)
        if not parsed:
            continue
        if reference and parsed < reference - timedelta(days=60):
            try:
                parsed = parsed.replace(year=reference.year)
                if parsed < reference - timedelta(days=60):
                    parsed = parsed.replace(year=reference.year + 1)
            except ValueError:
                continue
        return parsed.isoformat()
    return ""

def extract_status(text, deadline="", today=None):
    today = today or datetime.now(timezone.utc).date()
    deadline_date = parse_deadline(deadline)
    if deadline_date and deadline_date < today:
        return "Expired"
    if re.search(r"\b(?:closed|deadline passed|no longer accepting|position (?:has been )?filled)\b", text, re.I):
        return "Closed"
    if re.search(r"\b(?:reopen(?:ed)?|re-open(?:ed)?)\b", text, re.I):
        return "Reopened"
    if re.search(r"\b(?:open(?:ed)?|apply now|applications? (?:are )?live|registration (?:is )?open)\b", text, re.I):
        return "Open"
    return "New"

def posted_at(item):
    value = pick(item, "taken_at", "timestamp", "takenAt", "takenAtTimestamp", "takenAtIso", "date", "createdAt")
    if value in (None, ""):
        return ""
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except Exception:
        return str(value)

def source_url(item, source_type):
    for key in ("url", "postUrl", "post_url"):
        value = item.get(key)
        if isinstance(value, str) and value.startswith("http") and is_instagram_url(value):
            return value
    shortcode = pick(item, "shortCode", "shortcode")
    if shortcode:
        return f"https://www.instagram.com/p/{shortcode}/"
    if source_type == "Story":
        return f"https://www.instagram.com/stories/{USERNAME}/"
    return f"https://www.instagram.com/{USERNAME}/"

TITLE_ROLE_WORDS_RE = re.compile(
    r"\b(?:intern(?:ship)?s?|engineer(?:ing)?|developer|scientist|analyst|manager|associate|"
    r"fellow(?:ship)?s?|graduate|grad|apprentice(?:ship)?|co-?op|researcher|designer|residency|"
    r"scholar(?:ship)?s?|hackathon|summit|conference|workshop|trainee|specialist|architect|"
    r"programs?|swe|sde|apm|pm)\b",
    re.I,
)
TITLE_ACRONYMS = {
    "ai", "ml", "swe", "sde", "pm", "apm", "tpm", "ux", "ui", "us", "usa", "uk", "it", "bs",
    "ms", "phd", "aws", "gcp", "nyc", "sf", "hr", "qa", "ios", "api", "gpu", "llm", "nlp",
    "ar", "vr", "ev", "dc", "ii", "iii", "sre", "cs", "ece", "eecs", "ca", "ny", "tx", "wa",
    "va", "ga", "ma", "il", "nj", "nc", "pa", "mn", "mba", "gtm",
}
TITLE_SMALL_WORDS = {"and", "or", "of", "the", "for", "in", "on", "at", "to", "a", "an", "with"}
TITLE_QUERY_KEYS = {"jobname", "title", "job_title", "jobtitle", "position"}
DANGLING_END_RE = re.compile(
    r"\b(?:and|but|or|we|you|i|when|etc|the|a|an|to|for|of|with|is|are|our|your|this|that|at|in)\W*$",
    re.I,
)

def _title_word(word, first):
    lower = word.lower()
    if lower in TITLE_ACRONYMS:
        return lower.upper()
    if not first and lower in TITLE_SMALL_WORDS:
        return lower
    if any(ch.isupper() for ch in word[1:]):
        return word  # keep deliberate casing such as iOS or PhD
    return word[:1].upper() + word[1:].lower()

def title_from_url(url, organization=""):
    """Readable job title from an application URL slug.

    Many ATS links carry the real posting title, for example
    amazon.jobs/.../software-development-engineer-intern-aws-2027. Returns ""
    when the URL holds only IDs.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    candidates = [
        value for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() in TITLE_QUERY_KEYS and value
    ]
    candidates += [unquote(part) for part in reversed(parsed.path.split("/")) if part]
    for segment in candidates:
        segment = re.sub(r"\.(?:html?|aspx?|php)$", "", segment, flags=re.I)
        # Trailing requisition IDs such as _R-26-19948 or _JR123456.
        segment = re.sub(r"[_-]+(?:R|JR|REQ)?[-_]?\d[\d-]{3,}$", "", segment, flags=re.I)
        segment = re.sub(r"\bco-op\b", "Co-op", segment, flags=re.I)
        segment = re.sub(r"\b(?:xmlname|job[-_ ]posting[-_ ]title)\b", " ", segment, flags=re.I)
        words = [
            word for word in re.split(r"[\s_+,/|]+|(?<!co)-", segment, flags=re.I)
            if word and (
                re.fullmatch(r"20\d{2}", word)
                or not re.fullmatch(r"[0-9a-f]{8,}|\d{1,2}|[a-z]{0,4}\d{3,}[a-z]{0,2}", word, re.I)
            )
        ]
        words = [word.strip("()[]'\"") for word in words if word.strip("()[]'\"")]
        alpha = [word for word in words if re.search(r"[A-Za-z]{2,}", word)]
        phrase = " ".join(words)
        if len(alpha) < 2 or not TITLE_ROLE_WORDS_RE.search(phrase):
            continue
        org_words = org_key(organization)
        while words and org_words and org_key(words[0]) and org_words.startswith(org_key(words[0])):
            org_words = org_words[len(org_key(words[0])):]
            words = words[1:]
        words = words[:14]
        title = " ".join(_title_word(word, index == 0) for index, word in enumerate(words))
        if len(title) > 90:
            title = title[:90].rsplit(" ", 1)[0]
        if TITLE_ROLE_WORDS_RE.search(title):
            return title
    return ""

def _line_quality(line):
    line = re.sub(r"https?://\S+", "", line).strip(" •|-—_")
    if len(line) < 8 or len(line) > 180:
        return -1
    letters = sum(ch.isalpha() for ch in line)
    visible = sum(not ch.isspace() for ch in line)
    if not visible or letters / visible < 0.55:
        return -1
    words = re.findall(r"[A-Za-z0-9+#.&'-]+", line)
    if len(words) < 2:
        return -1
    score = letters + min(len(words), 12) * 4
    if OPPORTUNITY_RE.search(line):
        score += 100
    if ACTION_RE.search(line):
        score += 30
    return score

def usable_text_title(line):
    """True when an OCR/caption line is a readable opportunity name."""
    return bool(
        line
        and len(line) <= 100
        and OPPORTUNITY_RE.search(line)
        and TITLE_ROLE_WORDS_RE.search(line)
        and not NEGATIVE_CONTEXT_RE.search(line)
        and not line.startswith(("-", "(", "|", "@", "&"))
        and not line.endswith(("?", "&", ",", "|", "-", "—", "(", ">"))
        and not DANGLING_END_RE.search(line)
        and not line[:1].islower()
        and not re.search(
            r"\b(?:apply now|register now|join us|join our|link in bio|offers?|we are|we're|"
            r"you will|you'll|looking for|help build|thank you)\b",
            line,
            re.I,
        )
    )

CATEGORY_TITLE_NOUNS = {
    "Internship": "Internship",
    "New Grad / Early Career": "New Grad",
    "Job / Hiring": "Role",
}

def composed_title(category, role, season):
    primary_role = role.split(", ")[0] if role else ""
    noun = CATEGORY_TITLE_NOUNS.get(category, category)
    if primary_role and category in CATEGORY_TITLE_NOUNS:
        base = f"{primary_role} {noun}"
    else:
        base = primary_role or category
    first_season = season.split(", ")[0] if season else ""
    if first_season and first_season not in base:
        base = f"{base} · {first_season}"
    return base

def opportunity_title(org, category, role, text, link="", season=""):
    specific = title_from_url(link, org)
    if not specific and not org:
        lines = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("http"):
                continue
            score = _line_quality(line)
            if score >= 0:
                lines.append((score, line))
        best_line = max(lines, default=(0, ""))[1][:100].strip()
        if usable_text_title(best_line):
            specific = best_line
    specific = specific or composed_title(category, role, season)
    return f"{org} — {specific}" if org else specific

def normalize_identity_text(value):
    value = URL_RE.sub(" ", value or "")
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return " ".join(value.split())

SHORTCODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

def shortcode_to_media_id(shortcode):
    """Instagram post shortcodes are the media ID in URL-safe base64 digits."""
    if not shortcode or len(shortcode) > 12:
        return ""
    value = 0
    for char in shortcode:
        index = SHORTCODE_ALPHABET.find(char)
        if index < 0:
            return ""
        value = value * 64 + index
    return str(value)

def media_id_from_url(url, allow_shortcode=False):
    """Instagram media ID carried by a CDN URL or permalink, if any.

    CDN URLs from the Apify actors carry ig_cache_key, the media ID in
    base64; native Story items carry /stories/<user>/<media id>/ permalinks;
    posts carry /p/<shortcode>/. Keying on the media ID makes both scrapers
    agree on which Story is which.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    cache_key = dict(parse_qsl(parsed.query, keep_blank_values=True)).get("ig_cache_key", "")
    if cache_key:
        head = cache_key.split(".", 1)[0]
        try:
            decoded = base64.b64decode(head + "=" * (-len(head) % 4)).decode("ascii")
        except (ValueError, UnicodeDecodeError):
            decoded = ""
        return decoded if decoded.isdigit() else cache_key
    if is_instagram_url(url):
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 3 and parts[0] == "stories" and parts[2].isdigit():
            return parts[2]
        if allow_shortcode and len(parts) >= 2 and parts[0] in {"p", "reel", "reels", "tv"}:
            return shortcode_to_media_id(parts[1])
    return ""

def instagram_media_key(links):
    for url in links:
        media_id = media_id_from_url(url)
        if media_id:
            return media_id
    for url in links:
        media_id = media_id_from_url(url, allow_shortcode=True)
        if media_id:
            return media_id
    for url in links:
        try:
            if is_media_url(url):
                filename = Path(urlparse(url).path).name
                if filename:
                    return filename
        except Exception:
            continue
    return ""

def priority_label(row):
    return priority_for(row).title()

ENRICHMENT = {"version": 1, "pages": {}, "llm": {}}

def load_enrichment():
    """Cached job-page facts (by URL) and Claude extractions (by text hash)."""
    global ENRICHMENT
    try:
        data = json.loads(ENRICHMENT_PATH.read_text())
    except (FileNotFoundError, ValueError):
        data = {}
    ENRICHMENT = {"version": 1, "pages": data.get("pages") or {}, "llm": data.get("llm") or {}}
    return ENRICHMENT

def save_enrichment():
    ENRICHMENT_PATH.write_text(json.dumps(ENRICHMENT, indent=1, sort_keys=True, ensure_ascii=False) + "\n")

def text_key(text):
    return hashlib.sha256(str(text or "")[:12000].encode("utf-8", errors="ignore")).hexdigest()[:24]

def page_facts(url):
    return ENRICHMENT["pages"].get(url) or {} if url else {}

def llm_facts(text):
    return ENRICHMENT["llm"].get(text_key(text)) or {}

def display_org(name):
    """Canonical casing for a known company name; other names pass through."""
    name = " ".join(str(name or "").split())
    if not name or org_key(name) in {"zero2sudo", "greenhouse", "lever", "ashby", "workday", "linktree"}:
        return ""
    for variant in _slug_variants(org_key(name)):
        if variant in ORG_ALIASES:
            return ORG_ALIASES[variant]
        if variant in ORG_BY_KEY:
            return ORG_BY_KEY[variant]
    return name

def clean_page_title(title, organization="", require_role_word=True):
    """Job title from a page/API title, without site or company decoration.

    Page titles must name a role, because a page can be a search or landing
    page ("Careers at NVIDIA"); Claude's titles are already specific.
    """
    title = " ".join(str(title or "").split())
    if not title:
        return ""
    segments = [segment.strip() for segment in re.split(r"\s+\|\s+", title) if segment.strip()]
    title = next(
        (segment for segment in segments if not require_role_word or TITLE_ROLE_WORDS_RE.search(segment)),
        "",
    )
    if organization and title:
        org = re.escape(organization)
        title = re.sub(rf"^(?:{org})\s*[-–—:|]\s*", "", title, flags=re.I)
        title = re.sub(rf"\s*(?:[-–—|@]|\bat)\s*{org}\b.*$", "", title, flags=re.I)
    if (
        not title
        or len(title) > 120
        or re.match(r"(?:careers?|jobs?|join us|search)\b", title, re.I)
        or (require_role_word and not TITLE_ROLE_WORDS_RE.search(title))
    ):
        return ""
    return title

def plausible_page_deadline(value, reference):
    """Page deadlines (JSON-LD validThrough) a year out are ATS defaults."""
    parsed = parse_deadline(value)
    if not parsed:
        return ""
    base = reference or datetime.now(timezone.utc).date()
    return parsed.isoformat() if (parsed - base).days <= 150 else ""

def derive_fields(text, links, reference=None, today=None):
    """Every column that is computed from a post's text and links.

    New items and stored rows (re-processed from their Raw Text on each run)
    go through this one function, so extraction improvements apply to the
    whole tracker and an alert always matches what the tracker shows.

    Precedence per field: the live job page (when it could be read), then
    Claude's extraction (when ANTHROPIC_API_KEY is set), then the regex
    parsers. Both caches are deterministic between runs, so re-deriving is
    stable and makes no network calls.
    """
    external = external_links(links)
    destination = external[0] if external else ""
    page = page_facts(destination)
    llm = llm_facts(text)

    org = (
        display_org(llm.get("organization"))
        or extract_organization(text, links)
        or display_org(page.get("organization"))
    )
    category = llm.get("category") or extract_category(text)
    role = ", ".join(llm.get("roles") or []) or extract_roles(text)
    # A year inside "apply by Oct 15, 2026" is the deadline's, not the season's.
    season = llm.get("season") or extract_season(DEADLINE_RE.sub(" ", text))
    deadline = (
        plausible_page_deadline(page.get("deadline"), reference)
        or llm.get("deadline")
        or extract_deadline(text, reference)
    )
    specific = (
        clean_page_title(page.get("title"), org)
        or clean_page_title(llm.get("title"), org, require_role_word=False)
    )
    if specific:
        opportunity = f"{org} — {specific}" if org else specific
    else:
        opportunity = opportunity_title(org, category, role, text, destination, season)

    status = extract_status(text, deadline, today)
    if page.get("status") == "closed":
        status = "Closed"
    elif status != "Expired" and llm and not llm.get("is_opportunity", True) \
            and llm.get("confidence", 0) >= LLM_DROP_CONFIDENCE:
        status = "Not actionable"
    elif page.get("status") == "open" and status == "New":
        status = "Open"

    fields = {
        "Organization": org,
        "Opportunity": opportunity,
        "Category": category,
        "Role / Track": role,
        "Season / Year": season,
        "Location": page.get("location") or llm.get("location") or extract_location(text),
        "Deadline": deadline,
        "Application / Registration Link": destination,
        "Status": status,
    }
    fields["Priority"] = priority_label(fields)
    return fields

def record_id_for(record):
    return hashlib.sha256(record_semantic_key(record).encode("utf-8")).hexdigest()[:20]

def normalize_item(item, source_type):
    text = item_text(item)
    links = normalize_links(item)
    if not looks_actionable(text, links):
        return None

    posted = posted_at(item)
    reference = parse_iso_date(posted)
    record = {
        "ID": "",
        "First Seen": datetime.now(timezone.utc).isoformat(),
        "Posted At": posted,
        "Instagram Source": source_url(item, source_type),
        "Source Type": source_type,
        "Raw Text": text[:12000],
        "Actioned?": "No",
        "Notes": "",
    }
    record.update(derive_fields(text, links, reference))
    record["ID"] = record_id_for(record)
    return {header: record.get(header, "") for header in HEADERS}

def parse_iso_date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None

HEADER_FILL = PatternFill("solid", fgColor="17365D")
COLUMN_WIDTHS = [20, 22, 22, 20, 44, 24, 24, 18, 18, 14, 40, 40, 16, 60, 12, 12, 12, 28]

def create_workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Opportunities"
    ws.append(HEADERS)

    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for index, width in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = "A1:R1"
    write_dashboard(wb, [])
    wb.save(path)

def dashboard_metrics(records):
    def count(predicate):
        return sum(1 for record in records if predicate(record))

    return [
        ("Total opportunities", len(records)),
        ("Open / reopened", count(lambda r: r.get("Status") in {"Open", "Reopened"})),
        ("Not actioned", count(lambda r: not is_yes(r.get("Actioned?")))),
        ("Actioned", count(lambda r: is_yes(r.get("Actioned?")))),
        ("High priority", count(lambda r: r.get("Priority") == "High")),
        ("With a deadline", count(lambda r: bool(r.get("Deadline")))),
        ("Expired / closed", count(lambda r: r.get("Status") in {"Expired", "Closed"})),
        ("Not actionable (Claude)", count(lambda r: r.get("Status") == "Not actionable")),
        ("Internships", count(lambda r: r.get("Category") == "Internship")),
        ("Fellowships", count(lambda r: r.get("Category") == "Fellowship")),
        ("Scholarships / grants", count(lambda r: r.get("Category") == "Scholarship / Grant")),
    ]

def write_dashboard(wb, records):
    """Dashboard with literal values.

    openpyxl cannot compute formulas, so formula cells showed blank in GitHub's
    preview, Google Drive and other non-Excel viewers.
    """
    if "Dashboard" in wb.sheetnames:
        del wb["Dashboard"]
    dashboard = wb.create_sheet("Dashboard")
    dashboard["A1"] = "Zero2Sudo Opportunity Monitor"
    dashboard["A1"].font = Font(size=18, bold=True, color="FFFFFF")
    dashboard["A1"].fill = HEADER_FILL
    dashboard.merge_cells("A1:D1")
    dashboard.append([])
    dashboard.append(["Metric", "Value"])
    for cell in dashboard[3]:
        cell.font = Font(bold=True)
    for name, value in dashboard_metrics(records):
        dashboard.append([name, value])
    dashboard.column_dimensions["A"].width = 28
    dashboard.column_dimensions["B"].width = 18

def ensure_workbook():
    if not TRACKER_PATH.exists():
        create_workbook(TRACKER_PATH)

def workbook_records():
    wb = load_workbook(TRACKER_PATH, read_only=True, data_only=False)
    ws = wb["Opportunities"]
    headers = [cell.value for cell in ws[1]]
    records = [
        dict(zip(headers, row))
        for row in ws.iter_rows(min_row=2, values_only=True)
        if any(value not in (None, "") for value in row)
    ]
    wb.close()
    return records

def is_yes(value):
    return str(value or "").strip().lower() in {"yes", "y", "true", "x", "✓", "✔", "done", "applied"}

def normalize_actioned(value):
    return "Yes" if is_yes(value) else "No"

def record_links(record):
    values = [
        record.get("Application / Registration Link", ""),
        record.get("Instagram Source", ""),
    ]
    values.extend(URL_RE.findall(str(record.get("Raw Text", "") or "")))
    return [value for value in values if value]

def record_semantic_key(record):
    links = record_links(record)
    media = instagram_media_key(links)
    if media:
        return f"media:{media}"
    application = record.get("Application / Registration Link", "") or ""
    external = external_links([application])
    title = normalize_identity_text(record.get("Opportunity", ""))
    if external:
        return f"external:{clean_url(external[0])}|{title}"
    posted = str(record.get("Posted At", "") or "")[:13]
    org = normalize_identity_text(record.get("Organization", ""))
    raw = normalize_identity_text(record.get("Raw Text", ""))[:1000]
    return f"text:{posted}|{org}|{title}|{raw}"

JOB_ID_QUERY_KEYS = {"gh_jid", "jobid", "job_id", "jid", "token", "jobname", "postingid", "req", "reqid"}

def is_specific_link(url):
    """True when a URL identifies one posting rather than a generic careers page.

    Two Stories pointing at the same specific posting are the same opportunity
    reposted; two pointing at a generic careers page may not be.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if any(key.lower() in JOB_ID_QUERY_KEYS and value for key, value in parse_qsl(parsed.query)):
        return True
    for segment in (part for part in parsed.path.split("/") if part):
        if re.search(r"\d{5,}", segment):
            return True
        if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", segment, re.I):
            return True
        if len([word for word in re.split(r"[-_]+", segment) if re.search(r"[a-z]{2,}", word, re.I)]) >= 4:
            return True
    return False

def record_link_key(record):
    link = str(record.get("Application / Registration Link") or "")
    return f"link:{link}" if link and is_specific_link(link) else ""

def merge_record(target, source):
    merged = dict(target)
    for header in HEADERS:
        if header in {"Actioned?", "Notes"}:
            continue
        if merged.get(header) in (None, "") and source.get(header) not in (None, ""):
            merged[header] = source[header]
    if is_yes(source.get("Actioned?")):
        merged["Actioned?"] = "Yes"
    notes = []
    for value in (target.get("Notes"), source.get("Notes")):
        value = str(value or "").strip()
        if value and value not in notes:
            notes.append(value)
    merged["Notes"] = " | ".join(notes)
    return merged

def refresh_derived_fields(record, today=None):
    """Recompute extracted columns from the stored Raw Text.

    Raw Text holds the caption, OCR output and every link that was seen, so
    re-running extraction over it applies parser fixes retroactively without
    re-scraping or re-OCRing anything.
    """
    text = str(record.get("Raw Text") or "")
    if not text.strip():
        return record
    stored_link = record.get("Application / Registration Link") or ""
    links = ([stored_link] if stored_link else []) + URL_RE.findall(text)
    reference = parse_iso_date(record.get("Posted At")) or parse_iso_date(record.get("First Seen"))
    fields = derive_fields(text, links, reference, today)
    if stored_link:
        fields.pop("Application / Registration Link")
    record.update(fields)
    return record

def cleanup_records(records, today=None):
    cleaned = []
    index_by_key = {}
    invalid_links_cleared = 0
    duplicates_removed = 0
    for original in records:
        record = {header: original.get(header, "") for header in HEADERS}
        for header, value in record.items():
            if value is None:
                record[header] = ""
        application = record.get("Application / Registration Link", "") or ""
        if application:
            valid_external = external_links([application])
            if not valid_external:
                record["Application / Registration Link"] = ""
                invalid_links_cleared += 1
            else:
                record["Application / Registration Link"] = valid_external[0]
        refresh_derived_fields(record, today)
        record["Actioned?"] = normalize_actioned(record.get("Actioned?"))
        # IDs are permanent once assigned: Google Sheets edits and alert
        # batches are keyed by them.
        if not record.get("ID"):
            record["ID"] = record_id_for(record)
        keys = [key for key in (record_semantic_key(record), record_link_key(record)) if key]
        position = next((index_by_key[key] for key in keys if key in index_by_key), None)
        if position is not None:
            merged = merge_record(cleaned[position], record)
            # Keep the repost's text too, so fields re-derived from Raw Text on
            # later runs still see what the merged-away row contributed.
            texts = [str(cleaned[position].get("Raw Text") or ""), str(record.get("Raw Text") or "")]
            if texts[1].strip() and texts[1] not in texts[0]:
                merged["Raw Text"] = "\n\n".join(texts)[:24000]
            cleaned[position] = refresh_derived_fields(merged, today)
            duplicates_removed += 1
        else:
            position = len(cleaned)
            cleaned.append(record)
        for key in keys:
            index_by_key.setdefault(key, position)
    return cleaned, {
        "duplicates_removed": duplicates_removed,
        "invalid_links_cleared": invalid_links_cleared,
    }

def save_records(records):
    wb = load_workbook(TRACKER_PATH)
    ws = wb["Opportunities"]
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    for record in records:
        ws.append([record.get(header, "") for header in HEADERS])
        current = ws.max_row
        ws.row_dimensions[current].height = 45
        for col in range(1, len(HEADERS) + 1):
            ws.cell(current, col).alignment = Alignment(vertical="top", wrap_text=True)
        for col in (11, 12):
            cell = ws.cell(current, col)
            if cell.value:
                cell.hyperlink = cell.value
                cell.style = "Hyperlink"
    ws.auto_filter.ref = f"A1:R{max(ws.max_row, 1)}"
    for index, width in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    write_dashboard(wb, records)
    wb.save(TRACKER_PATH)

def migrate_workbook(manual_fields=None):
    """Clean, de-duplicate and re-derive every stored row.

    Google Sheets edits are applied before anything is merged so that a user's
    Actioned?/Notes values follow a row into whatever it is merged with.
    """
    records = workbook_records()
    stored = [
        {header: "" if record.get(header) is None else record.get(header) for header in HEADERS}
        for record in records
    ]
    working = [dict(record) for record in stored]
    if manual_fields:
        working = apply_manual_fields(working, manual_fields)
    cleaned, stats = cleanup_records(working)
    changed = cleaned != stored
    if changed:
        save_records(cleaned)
    stats.update({"before": len(records), "after": len(cleaned), "changed": changed})
    return stats

def apply_manual_fields(records, manual_fields):
    for record in records:
        values = manual_fields.get(str(record.get("ID", "")), {})
        if values.get("Actioned?") not in (None, ""):
            record["Actioned?"] = normalize_actioned(values["Actioned?"])
        if values.get("Notes") not in (None, ""):
            record["Notes"] = values["Notes"]
    return records

def existing_ids():
    wb = load_workbook(TRACKER_PATH, read_only=True)
    ws = wb["Opportunities"]
    ids = {str(row[0]) for row in ws.iter_rows(min_row=2, max_col=1, values_only=True) if row[0]}
    wb.close()
    return ids

def append_rows(rows):
    if not rows:
        return
    save_records(workbook_records() + list(rows))

def find_new_rows(records, candidates):
    """Candidates that are neither already tracked nor reposts of a tracked posting."""
    known = set()
    for record in records:
        known.add(record_semantic_key(record))
        link_key = record_link_key(record)
        if link_key:
            known.add(link_key)
    new_rows = []
    for record in candidates:
        keys = {record_semantic_key(record), record_link_key(record)} - {""}
        if keys & known:
            continue
        known.update(keys)
        new_rows.append(record)
    return new_rows

def tracker_url():
    if GOOGLE_SHEET_ID:
        return f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit"
    if GITHUB_REPOSITORY:
        return f"https://github.com/{GITHUB_REPOSITORY}/blob/main/{LIVE_VIEW_PATH.name}"
    return str(LIVE_VIEW_PATH)

PRIORITY_ICONS = {"High": "🔥", "Medium": "⭐"}
CLOSING_SOON_DAYS = 14
RECENT_DAYS = 7

def _md(value):
    return " ".join(str(value or "").split()).replace("|", "\\|")

def _month_day(value):
    return f"{value:%b} {value.day}"  # portable; "%-d" fails on Windows

def _short_date(value):
    parsed = parse_iso_date(value)
    return _month_day(parsed) if parsed else ""

def _deadline_display(value, today):
    parsed = parse_deadline(value)
    if not parsed:
        return _md(value) or "—"
    days = (parsed - today).days
    label = _month_day(parsed)
    if parsed.year != today.year:
        label += f", {parsed.year}"
    if 0 <= days <= CLOSING_SOON_DAYS:
        label += " (today)" if days == 0 else f" ({days}d)"
    return label

def _link_cell(row, today):
    application = row.get("Application / Registration Link") or ""
    if application:
        return f"[Apply ↗](<{application}>)"
    source = row.get("Instagram Source") or ""
    if not source:
        return "—"
    if row.get("Source Type") == "Story":
        seen = parse_iso_date(row.get("First Seen"))
        if seen and (today - seen).days >= 1:
            return f"[Story](<{source}>) (expired)"
        return f"[Story](<{source}>)"
    return f"[Post](<{source}>)"

def _live_table(rows, today):
    lines = [
        "| | Opportunity | Type | Deadline | Seen | Link |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        icon = PRIORITY_ICONS.get(str(row.get("Priority") or ""), "")
        title = _md(row.get("Opportunity") or row.get("Category") or "Opportunity")
        lines.append(
            f"| {icon} | {title} | {_md(row.get('Category'))} | "
            f"{_deadline_display(row.get('Deadline'), today)} | "
            f"{_short_date(row.get('First Seen'))} | {_link_cell(row, today)} |"
        )
    return lines

def write_live_view(records, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.date()
    rows = sorted(records, key=lambda row: str(row.get("First Seen", "") or ""), reverse=True)
    actioned = [row for row in rows if is_yes(row.get("Actioned?"))]
    open_rows = [row for row in rows if not is_yes(row.get("Actioned?"))]
    past = [row for row in open_rows if row.get("Status") in {"Expired", "Closed"}]
    filtered = [row for row in open_rows if row.get("Status") == "Not actionable"]
    active = [
        row for row in open_rows if row.get("Status") not in {"Expired", "Closed", "Not actionable"}
    ]

    def deadline_in_window(row):
        parsed = parse_deadline(row.get("Deadline"))
        return bool(parsed) and 0 <= (parsed - today).days <= CLOSING_SOON_DAYS

    def is_recent(row):
        seen = parse_iso_date(row.get("First Seen"))
        return bool(seen) and (today - seen).days < RECENT_DAYS

    closing = sorted(
        (row for row in active if deadline_in_window(row)),
        key=lambda row: parse_deadline(row.get("Deadline")),
    )
    recent = [row for row in active if is_recent(row) and row not in closing]
    earlier = [row for row in active if not is_recent(row) and row not in closing]

    lines = [
        "# Zero2Sudo Opportunity Tracker",
        "",
        f"_Updated {_month_day(now)}, {now:%Y %H:%M} UTC · {len(rows)} tracked · "
        f"{len(recent) + sum(1 for row in closing if is_recent(row))} new this week · "
        f"{len(actioned)} actioned_",
        "",
    ]
    if GOOGLE_SHEET_ID:
        lines += [
            f"Mark rows **Actioned?** or add **Notes** in the "
            f"[Google Sheet]({tracker_url()}); edits sync back here hourly.",
            "",
        ]
    lines += [
        "🔥 high priority · ⭐ matches SWE / AI / data interests · "
        "Deadlines are read from the post and may be missing.",
        "",
    ]
    sections = [
        (f"⏰ Closing within {CLOSING_SOON_DAYS} days", closing),
        (f"🆕 New in the last {RECENT_DAYS} days", recent),
        ("📋 Earlier", earlier),
    ]
    for heading, section_rows in sections:
        if not section_rows:
            continue
        lines += [f"## {heading} ({len(section_rows)})", ""]
        lines += _live_table(section_rows, today)
        lines.append("")
    for heading, section_rows in (
        ("✅ Actioned", actioned),
        ("⌛ Past deadline or posting closed", past),
        ("🙈 Probably not an opportunity (Claude)", filtered),
    ):
        if not section_rows:
            continue
        lines += [
            f"<details><summary><b>{heading} ({len(section_rows)})</b></summary>",
            "",
        ]
        lines += _live_table(section_rows, today)
        lines += ["", "</details>", ""]
    if not rows:
        lines += ["_Nothing tracked yet. New opportunities appear here after the next check._", ""]
    LIVE_VIEW_PATH.write_text("\n".join(lines).rstrip() + "\n")

def load_state():
    if not STATE_PATH.exists():
        return {"version": 1, "pending_batches": [], "delivered_batch_ids": []}
    state = json.loads(STATE_PATH.read_text())
    state.setdefault("version", 1)
    state.setdefault("pending_batches", [])
    state.setdefault("delivered_batch_ids", [])
    return state

def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")

def queue_batch(rows):
    state = load_state()
    if not rows:
        save_state(state)
        return ""
    batch_id = hashlib.sha256(
        "|".join(sorted(str(row["ID"]) for row in rows)).encode("utf-8")
    ).hexdigest()[:20]
    known = set(state["delivered_batch_ids"])
    known.update(batch["id"] for batch in state["pending_batches"])
    if batch_id not in known:
        state["pending_batches"].append({
            "id": batch_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "rows": rows,
        })
        save_state(state)
    return batch_id

PREFERRED_ROLE_RE = re.compile(
    r"\b(software engineering|machine learning|artificial intelligence|"
    r"ai|data engineering|data science)\b",
    re.I,
)
PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "NORMAL": 2}

def priority_for(row):
    """HIGH for a HIGH_PRIORITY_ORGS company, MEDIUM for SWE / AI / data roles."""
    org_words = [org_key(word) for word in str(row.get("Organization") or "").split()]
    org_words = [word for word in org_words if word]
    for name in HIGH_PRIORITY_ORGS:
        high_words = [org_key(word) for word in name.split() if org_key(word)]
        if high_words and org_words[:len(high_words)] == high_words:
            return "HIGH"
        if high_words and "".join(org_words) == "".join(high_words):
            return "HIGH"  # "ScaleAI" vs "Scale AI"
    text = " ".join(str(row.get(key) or "") for key in ("Opportunity", "Role / Track"))
    if PREFERRED_ROLE_RE.search(text):
        return "MEDIUM"
    return "NORMAL"

def rank_rows(rows):
    return sorted(rows, key=lambda row: PRIORITY_RANK[priority_for(row)])

def clean_alert_title(row):
    org = row.get("Organization") or ""
    opp = row.get("Opportunity") or row.get("Category") or "New opportunity"
    if org and not opp.lower().startswith(org.lower()):
        return f"{org} — {opp}"
    return opp

def _deadline_note(row):
    parsed = parse_deadline(row.get("Deadline"))
    if parsed:
        return f"due {_month_day(parsed)}"
    return row.get("Deadline") or ""

def ntfy_alert(rows, batch_id=""):
    if not rows or not NTFY_TOPIC:
        return True

    ranked = rank_rows(rows)
    top = ranked[0]
    priority = priority_for(top)
    prefix = "🚨" if priority == "HIGH" else "📣"
    title = f"{prefix} {priority}: {clean_alert_title(top)}"
    if len(rows) > 1:
        title += f" (+{len(rows) - 1} more)"

    body_lines = []
    for row in ranked[:5]:
        meta = " · ".join(x for x in [row.get("Category", ""), _deadline_note(row)] if x)
        body_lines.append(f"[{priority_for(row)}] {clean_alert_title(row)}" + (f" — {meta}" if meta else ""))
        link = row.get("Application / Registration Link") or row.get("Instagram Source") or ""
        if link:
            body_lines.append(link)
        body_lines.append("")
    if len(ranked) > 5:
        body_lines.append(f"+ {len(ranked) - 5} more in the tracker: {tracker_url()}")

    # JSON publishing: HTTP header values are latin-1 only, so emoji and
    # em-dashes in a Title header raise UnicodeEncodeError before sending.
    payload = {
        "topic": NTFY_TOPIC,
        "title": title[:250],
        "message": "\n".join(body_lines).strip(),
        "tags": ["rotating_light", "briefcase"] if priority == "HIGH" else ["briefcase"],
        "priority": 5 if priority == "HIGH" else (4 if priority == "MEDIUM" else 3),
    }
    top_link = top.get("Application / Registration Link") or top.get("Instagram Source") or ""
    if top_link:
        payload["click"] = top_link
        payload["actions"] = [{"action": "view", "label": "Apply / Open", "url": top_link, "clear": True}]
    headers = {"Authorization": f"Bearer {NTFY_TOKEN}"} if NTFY_TOKEN else {}

    response = requests.post(NTFY_SERVER.rstrip("/"), json=payload, headers=headers, timeout=30)
    if response.status_code >= 300:
        raise RuntimeError(f"ntfy push failed with status {response.status_code}.")
    print(f"Sent ntfy push notification for batch {batch_id or '(unbatched)'}.")
    return True

def github_issue(rows, batch_id=""):
    if not rows or not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        return True

    owner = GITHUB_REPOSITORY.split("/", 1)[0]
    marker = f"<!-- zero2sudo-batch:{batch_id} -->" if batch_id else ""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    issue_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues"
    if marker:
        existing = requests.get(
            issue_url,
            headers=headers,
            params={"state": "all", "per_page": 100},
            timeout=30,
        )
        existing.raise_for_status()
        if any(marker in (issue.get("body") or "") for issue in existing.json()):
            print(f"GitHub alert already exists for batch {batch_id}.")
            return True

    ranked = rank_rows(rows)
    noun = "opportunity" if len(rows) == 1 else "opportunities"
    lines = [
        marker,
        f"@{owner}",
        "",
        f"Zero2Sudo shared **{len(rows)} new actionable {noun}**.",
        "",
        "| | Opportunity | Type | Deadline | Link |",
        "|---|---|---|---|---|",
    ]
    for row in ranked[:20]:
        icon = {"HIGH": "🔥", "MEDIUM": "⭐"}.get(priority_for(row), "")
        link = row.get("Application / Registration Link") or row.get("Instagram Source") or ""
        link_cell = f"[Apply ↗](<{link}>)" if row.get("Application / Registration Link") else (
            f"[Story](<{link}>)" if link else "—"
        )
        lines.append(
            f"| {icon} | {_md(clean_alert_title(row))} | {_md(row.get('Category'))} | "
            f"{_md(_deadline_note(row)) or '—'} | {link_cell} |"
        )

    if len(rows) > 20:
        lines.extend(["", f"_Plus {len(rows) - 20} more in the tracker._"])

    lines.extend([
        "",
        f"Live tracker: [Open the current tracker]({tracker_url()})",
        "",
        f"Excel backup: [Download workbook](https://github.com/{GITHUB_REPOSITORY}/blob/main/{TRACKER_PATH.name})",
        "",
        "_Created automatically by the hourly Zero2Sudo monitor._",
    ])

    top = ranked[0]
    top_priority = priority_for(top)
    top_title = clean_alert_title(top)
    prefix = "🚨" if top_priority == "HIGH" else "📣"
    if len(rows) == 1:
        title = f"{prefix} [{top_priority}] {top_title} — APPLY / OPEN"
    else:
        title = f"{prefix} [{top_priority}] {top_title} + {len(rows) - 1} more"
    payload = {"title": title[:250], "body": "\n".join(lines), "assignees": [owner]}
    response = requests.post(issue_url, headers=headers, json=payload, timeout=30)

    # Some repository permission combinations reject assignment. The @mention in
    # the body still alerts the owner, so retry without assignees rather than
    # losing the alert entirely.
    if response.status_code == 422:
        payload.pop("assignees", None)
        response = requests.post(issue_url, headers=headers, json=payload, timeout=30)

    if response.status_code >= 300:
        raise RuntimeError(f"Could not create GitHub alert issue: {response.status_code}.")
    print(f"Created alert issue: {response.json().get('html_url', '')}")
    return True

def deliver_pending_batches():
    state = load_state()
    delivered = set(state["delivered_batch_ids"])
    remaining = []
    for batch in state["pending_batches"]:
        batch_id = batch["id"]
        if batch_id in delivered:
            continue
        try:
            github_issue(batch["rows"], batch_id)
            ntfy_alert(batch["rows"], batch_id)
        except Exception as exc:
            remaining.append(batch)
            print(f"::warning::Batch {batch_id} remains pending: {exc}")
            continue
        delivered.add(batch_id)
    state["pending_batches"] = remaining
    state["delivered_batch_ids"] = sorted(delivered)[-500:]
    save_state(state)
    if remaining:
        raise RuntimeError(f"{len(remaining)} notification batch(es) remain pending.")
    return len(delivered)

def pull_google_manual_fields():
    if not GOOGLE_SERVICE_ACCOUNT_JSON or not GOOGLE_SHEET_ID:
        if GOOGLE_SYNC_REQUIRED:
            raise RuntimeError(
                "Google Sheets sync is required but GOOGLE_SERVICE_ACCOUNT_JSON "
                "or GOOGLE_SHEET_ID is missing."
            )
        return {}
    from google_sheets_sync import fetch_manual_fields

    return fetch_manual_fields(GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID)

def sync_google_sheet():
    if not GOOGLE_SERVICE_ACCOUNT_JSON or not GOOGLE_SHEET_ID:
        if GOOGLE_SYNC_REQUIRED:
            raise RuntimeError(
                "Google Sheets sync is required but its repository secrets are missing."
            )
        print("Google Sheets is not configured; LATEST.md is the permanent live view.")
        return False
    from google_sheets_sync import sync_records

    records = workbook_records()
    merged = sync_records(
        GOOGLE_SERVICE_ACCOUNT_JSON,
        GOOGLE_SHEET_ID,
        HEADERS,
        records,
        dashboard_metrics,
    )
    for record in merged:
        record["Actioned?"] = normalize_actioned(record.get("Actioned?"))
    if merged != records:
        save_records(merged)
        write_live_view(merged)
    print(f"Verified {len(merged)} rows in Google Sheets.")
    return True

def store_page_facts(url, facts):
    """Merge a fresh check into the cache without losing good data to an error."""
    old = ENRICHMENT["pages"].get(url) or {}
    facts = {key: value for key, value in facts.items() if key != "description"}
    if facts["status"] == "unknown" and old:
        merged = dict(old)
        merged["checked_at"] = facts["checked_at"]
        if facts.get("error"):
            merged["last_error"] = facts["error"]
        if facts.get("title") and not merged.get("title"):
            merged["title"] = facts["title"]
    elif facts["status"] == "closed":
        merged = dict(old)
        merged.update(facts)
        merged["closed_at"] = old.get("closed_at") or facts["checked_at"]
    else:
        merged = facts
    ENRICHMENT["pages"][url] = merged
    return merged

def refresh_job_pages(records, force_urls=(), budget=None):
    """Read job pages for new links and re-check stale ones for takedowns.

    Returns {url: description} for pages read this run, which are only held in
    memory to give Claude context; the cache keeps the short facts.
    """
    if not JOB_PAGES_ENABLED:
        return {}
    budget = PAGE_CHECKS_PER_RUN if budget is None else budget
    now = datetime.now(timezone.utc)
    stale = []
    for record in records:
        url = record.get("Application / Registration Link") or ""
        if not url or is_yes(record.get("Actioned?")) or record.get("Status") == "Expired":
            continue
        entry = ENRICHMENT["pages"].get(url)
        if entry and entry.get("status") == "closed":
            continue
        try:
            checked = datetime.fromisoformat(entry["checked_at"]) if entry else None
        except (KeyError, ValueError):
            checked = None
        if checked and now - checked < timedelta(hours=PAGE_RECHECK_HOURS):
            continue
        stale.append((checked.isoformat() if checked else "", url))
    urls = list(dict.fromkeys(list(force_urls) + [url for _, url in sorted(stale)][:budget]))
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(job_pages.fetch_job_facts, urls))
    descriptions = {}
    for url, facts in zip(urls, results):
        descriptions[url] = facts.get("description", "")
        before = (ENRICHMENT["pages"].get(url) or {}).get("status")
        after = store_page_facts(url, facts)["status"]
        ENRICHMENT_REPORT["pages_checked"] += 1
        if after == "closed" and before != "closed":
            ENRICHMENT_REPORT["postings_closed"] += 1
    return descriptions

_extractor = None

def extractor():
    global _extractor
    if _extractor is None:
        from llm_extraction import Extractor

        categories = [label for label, _ in CATEGORIES] + ["Other Opportunity"]
        _extractor = Extractor(categories, [label for label, _ in ROLE_PATTERNS])
    return _extractor

def run_llm_extraction(records, budget, descriptions=None):
    """Claude extraction for rows whose text has not been extracted yet."""
    if not LLM_ENABLED or budget <= 0:
        return 0
    descriptions = descriptions or {}
    targets, seen = [], set()
    for record in records:
        text = str(record.get("Raw Text") or "")
        key = text_key(text)
        if text.strip() and key not in ENRICHMENT["llm"] and key not in seen:
            seen.add(key)
            targets.append(record)
    targets = targets[:budget]
    if not targets:
        return 0

    def work(record):
        text = str(record.get("Raw Text") or "")
        link = record.get("Application / Registration Link") or ""
        page = dict(page_facts(link))
        if descriptions.get(link):
            page["description"] = descriptions[link]
        posted = str(record.get("Posted At") or record.get("First Seen") or "")[:10]
        return text_key(text), extractor().extract(text, link, posted, page)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for key, facts in pool.map(work, targets):
            if facts:
                ENRICHMENT["llm"][key] = facts
    return len(targets)

def enrich_rows(rows):
    """Read job pages and run Claude for new rows, then re-derive their fields.

    Rows Claude is confident are not opportunities (a meme, advice, an offer
    celebration) are dropped here so they never alert.
    """
    if not rows:
        return rows
    links = [row.get("Application / Registration Link") for row in rows]
    descriptions = refresh_job_pages([], force_urls=[link for link in links if link])
    run_llm_extraction(rows, len(rows), descriptions)
    kept = []
    for row in rows:
        refresh_derived_fields(row)
        if row.get("Status") == "Not actionable":
            ENRICHMENT_REPORT["filtered_by_llm"] += 1
            print(f"Skipped (Claude: not an opportunity): {row.get('Opportunity')}")
            continue
        kept.append(row)
    return kept

def newest_first(records):
    return sorted(records, key=lambda row: str(row.get("First Seen") or ""), reverse=True)

def collect_candidates(fixture=None):
    """Normalized, actionable items from Apify, or from a local JSON fixture.

    A fixture is either a list of items (treated as Stories) or an object with
    "stories" and/or "posts" lists in the Apify actor output format.
    """
    if fixture:
        data = json.loads(Path(fixture).read_text())
        if isinstance(data, list):
            data = {"stories": data}
        sources = [(data.get("stories", []), "Story"), (data.get("posts", []), "Post / Reel")]
    else:
        sources = [(fetch_stories(), "Story"), (fetch_posts(), "Post / Reel")]
    candidates = []
    for items, source_type in sources:
        for item in items:
            record = normalize_item(item, source_type)
            if record:
                candidates.append(record)
    return candidates

def print_rows(rows):
    for row in rank_rows(rows):
        print(f"  [{priority_for(row)}] {clean_alert_title(row)}")
        details = " · ".join(
            value for value in (
                row.get("Category"), row.get("Deadline") and f"deadline {row['Deadline']}",
                row.get("Location"), row.get("Application / Registration Link"),
            ) if value
        )
        if details:
            print(f"      {details}")

def dry_run(fixture=None):
    """Show what a check would add, without writing files or sending alerts.

    A real dry run reads job pages and calls Claude for the new rows (in
    memory only); a fixture run stays fully offline.
    """
    load_enrichment()
    records = []
    if TRACKER_PATH.exists():
        records, _ = cleanup_records(workbook_records())
    new_rows = find_new_rows(records, collect_candidates(fixture))
    if not fixture:
        new_rows = enrich_rows(new_rows)
    print(f"Dry run: {len(new_rows)} new opportunity row(s) would be added "
          f"to the {len(records)} already tracked.")
    print_rows(new_rows)
    return new_rows

def main(defer_notifications=False):
    if not APIFY_TOKEN and not IG_SESSIONID and SCRAPER != "native":
        raise SystemExit(
            "No scraper is configured. Set IG_SESSIONID (native Instagram scraper) and/or "
            "APIFY_TOKEN as GitHub Actions secrets, or export them locally. "
            "Try --fixture tests/fixtures/sample_items.json for an offline demo."
        )

    ensure_workbook()
    load_enrichment()
    # Read Google Sheets edits before cleanup can merge rows, so a user's
    # Actioned?/Notes values are carried into whatever row survives.
    manual_fields = pull_google_manual_fields()
    # Re-check stale job links for takedowns and backfill Claude extraction a
    # few rows at a time; migrate_workbook then re-derives with the results.
    existing = workbook_records()
    descriptions = refresh_job_pages(existing)
    run_llm_extraction(newest_first(existing), LLM_BACKFILL_PER_RUN, descriptions)
    save_enrichment()
    cleanup = migrate_workbook(manual_fields)
    records = workbook_records()
    known_ids = {str(record.get("ID")) for record in records if record.get("ID")}

    new_rows = find_new_rows(records, collect_candidates())
    new_rows = enrich_rows(new_rows)
    save_enrichment()

    append_rows(new_rows)
    persisted = existing_ids()
    expected = known_ids | {row["ID"] for row in new_rows}
    if persisted != expected:
        raise RuntimeError("Saved tracker IDs do not match the expected rows.")
    final_records = workbook_records()
    write_live_view(final_records)
    batch_id = queue_batch(new_rows)
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "previous_rows": len(known_ids),
        "new_rows": len(new_rows),
        "total_rows": len(persisted),
        "tracker_sha256": hashlib.sha256(TRACKER_PATH.read_bytes()).hexdigest(),
        "cleanup": cleanup,
        "notification_batch_id": batch_id,
        "google_sheets_configured": bool(GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEET_ID),
        "live_tracker_url": tracker_url(),
        "scrapers": SCRAPE_REPORT["scrapers"],
        "scrape_warnings": SCRAPE_REPORT["warnings"],
        "enrichment": dict(
            ENRICHMENT_REPORT,
            llm=_extractor.usage if _extractor else ({"calls": 0} if LLM_ENABLED else "disabled"),
        ),
    }
    STATUS_PATH.write_text(json.dumps(report, indent=2) + "\n")
    if not defer_notifications:
        sync_google_sheet()
        deliver_pending_batches()
    print(f"Added {len(new_rows)} new opportunity row(s).")
    print_rows(new_rows)
    print(f"Verified {len(persisted)} total rows in {TRACKER_PATH}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track actionable opportunities posted by an Instagram account.")
    parser.add_argument("--defer-notifications", action="store_true",
                        help="save and queue alerts, but send them later with --notify")
    parser.add_argument("--notify", action="store_true", help="send queued alerts")
    parser.add_argument("--sync-google", action="store_true", help="sync the tracker to Google Sheets")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be added; write nothing and send nothing")
    parser.add_argument("--fixture", metavar="JSON",
                        help="read items from a local JSON file instead of Apify (implies --dry-run)")
    args = parser.parse_args()
    if args.notify:
        deliver_pending_batches()
    elif args.sync_google:
        sync_google_sheet()
    elif args.dry_run or args.fixture:
        if not args.fixture and not (APIFY_TOKEN or IG_SESSIONID):
            raise SystemExit("--dry-run needs IG_SESSIONID or APIFY_TOKEN, or use --fixture FILE to run offline.")
        dry_run(args.fixture)
    else:
        main(defer_notifications=args.defer_notifications)
