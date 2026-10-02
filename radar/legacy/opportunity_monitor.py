import base64
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

import requests
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image
import pytesseract

try:  # Some Story media is HEIC, which Pillow cannot open on its own.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

USERNAME = os.getenv("IG_USERNAME", "zero2sudo").lstrip("@")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
TRACKER_PATH = Path(os.getenv("TRACKER_PATH", "Zero2Sudo_Opportunity_Tracker.xlsx"))
LIVE_VIEW_PATH = Path(os.getenv("LIVE_VIEW_PATH", "LATEST.md"))

ENRICHMENT_PATH = Path(os.getenv("ENRICHMENT_PATH", "enrichment_cache.json"))


LLM_ENABLED = bool(
    os.getenv("ANTHROPIC_API_KEY", "").strip() or os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
) and os.getenv("LLM_EXTRACTION", "on").strip().lower() not in {"0", "off", "false", "no"}

STORY_ACTOR = os.getenv("STORY_ACTOR", "data-slayer/instagram-stories-scraper")

GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()

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


NEGATIVE_CONTEXT_RE = re.compile(
    r"\b(got|received|accepted|landed)\s+(?:an?\s+)?(?:intern(?:ship)?\s+)?offer\b|"
    r"\boffer\s*[+&/]?\s*process\b|\bhas anyone\b|\bdid anyone\b|"
    r"\bno sign[- ]?up\b|\bno registration\b|\bhiring happens\b|"
    r"\bapplication process\b|\binterview process\b|\brecap\b|"
    r"\bthis is why\b|\bwhat are my chances\b",
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

def _known_org(key):
    """Known company for an org_key, trying its slug variants; "" if none."""
    for variant in _slug_variants(key):
        if variant in ORG_ALIASES:
            return ORG_ALIASES[variant]
        if variant in ORG_BY_KEY:
            return ORG_BY_KEY[variant]
    return ""

def canonical_org(raw):
    """Map a host label or path slug such as 'doordashusa' to 'DoorDash'."""
    raw = unquote(str(raw or "")).strip()
    key = org_key(raw)
    if not key:
        return ""
    known = _known_org(key)
    if known:
        return known
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


def text_key(text):
    return hashlib.sha256(str(text or "")[:12000].encode("utf-8", errors="ignore")).hexdigest()[:24]


def display_org(name):
    """Canonical casing for a known company name; other names pass through."""
    name = " ".join(str(name or "").split())
    if not name or org_key(name) in {"zero2sudo", "greenhouse", "lever", "ashby", "workday", "linktree"}:
        return ""
    return _known_org(org_key(name)) or name


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


def workbook_records(path=None):
    wb = load_workbook(path or TRACKER_PATH, read_only=True, data_only=False)
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


def save_records(records, path=None):
    path = path or TRACKER_PATH
    wb = load_workbook(path)
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
    wb.save(path)


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

def write_live_view(records, now=None, path=None):
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
    (path or LIVE_VIEW_PATH).write_text("\n".join(lines).rstrip() + "\n")


_extractor = None

def extractor():
    global _extractor
    if _extractor is None:
        from radar.legacy.llm_extraction import Extractor

        categories = [label for label, _ in CATEGORIES] + ["Other Opportunity"]
        _extractor = Extractor(categories, [label for label, _ in ROLE_PATTERNS])
    return _extractor
