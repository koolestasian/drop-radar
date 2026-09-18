#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image
import pytesseract

USERNAME = os.getenv("IG_USERNAME", "zero2sudo").lstrip("@")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
TRACKER_PATH = Path(os.getenv("TRACKER_PATH", "Zero2Sudo_Opportunity_Tracker.xlsx"))
STATUS_PATH = Path(os.getenv("STATUS_PATH", "monitor_status.json"))
STATE_PATH = Path(os.getenv("STATE_PATH", "monitor_state.json"))
LIVE_VIEW_PATH = Path(os.getenv("LIVE_VIEW_PATH", "LATEST.md"))

STORY_ACTOR = os.getenv("STORY_ACTOR", "data-slayer/instagram-stories-scraper")
POST_ACTOR = os.getenv("POST_ACTOR", "apify/instagram-scraper")

GITHUB_TOKEN = os.getenv("GH_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
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
    "Atlassian", "Asana", "Dropbox", "Pinterest", "Reddit", "Snap", "TikTok", "ByteDance"
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
    response = requests.post(
        actor_url(actor_id),
        params={"token": APIFY_TOKEN, "timeout": REQUEST_TIMEOUT},
        json=payload,
        timeout=REQUEST_TIMEOUT + 30,
    )
    response.raise_for_status()
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

def fetch_stories():
    try:
        return run_actor(STORY_ACTOR, {"usernames": [USERNAME]})
    except Exception as exc:
        raise RuntimeError("Story scrape failed; this check is incomplete.") from None

def fetch_posts():
    payload = {
        "directUrls": [f"https://www.instagram.com/{USERNAME}/"],
        "resultsType": "posts",
        "resultsLimit": 10,
        "onlyPostsNewerThan": "2 days",
        "skipPinnedPosts": True,
    }
    try:
        return run_actor(POST_ACTOR, payload)
    except Exception as exc:
        raise RuntimeError("Post/reel scrape failed; this check is incomplete.") from None

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
            valid = parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
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
            image = Image.open(temp.name).convert("RGB")
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

def _pretty_org(value):
    value = re.sub(r"[-_]+", " ", value or "").strip()
    return " ".join(part.upper() if len(part) <= 3 else part.capitalize() for part in value.split())

def organization_from_links(links):
    for url in external_links(links):
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower().removeprefix("www.")

            for domain, organization in DOMAIN_ORGS.items():
                if host == domain or host.endswith("." + domain):
                    return organization

            # Common ATS patterns encode the company in a subdomain/path.
            labels = host.split(".")
            if host.endswith("myworkdayjobs.com") and labels:
                candidate = labels[0]
                if candidate not in {"wd1", "wd2", "wd3", "wd5"}:
                    return _pretty_org(candidate)

            if host in {"jobs.lever.co", "boards.greenhouse.io", "job-boards.greenhouse.io"}:
                path_parts = [p for p in parsed.path.split("/") if p]
                if path_parts:
                    return _pretty_org(path_parts[0])

            # apply.company.com / careers.company.com / jobs.company.com
            if len(labels) >= 2 and labels[0] in {"apply", "careers", "career", "jobs", "job"}:
                return _pretty_org(labels[1])
        except Exception:
            pass
    return ""

def extract_organization(text, links):
    from_link = organization_from_links(links)
    if from_link:
        return from_link
    for org in KNOWN_ORGS:
        if re.search(rf"\b{re.escape(org)}\b", text, re.I):
            return org
    return ""

def extract_category(text):
    categories = [
        ("Internship", r"\bintern(ship)?\b"),
        ("New Grad / Early Career", r"\bnew grad|early career|entry[- ]level\b"),
        ("Job / Hiring", r"\bhiring|job opening|open role|student job\b"),
        ("Fellowship", r"\bfellowship\b"),
        ("Scholarship / Grant", r"\bscholarship|grant|stipend\b"),
        ("Hackathon / Competition", r"\bhackathon|competition|challenge|pitch competition\b"),
        ("Conference / Summit", r"\bconference|summit\b"),
        ("Recruiting / Career Event", r"\bcareer fair|recruiting event|direct consideration\b"),
        ("Networking", r"\bnetworking event|meetup|coffee chat\b"),
        ("Workshop / Info Session", r"\bworkshop|webinar|info session|information session|office hours|resume review\b"),
        ("Mentorship / Cohort", r"\bmentorship|mentor program|cohort\b"),
        ("Student / Campus Program", r"\bambassador program|campus program|student program|university program\b"),
        ("Research", r"\bresearch opportunity|research program|research intern\b"),
        ("Apprenticeship / Externship", r"\bapprenticeship|externship\b"),
        ("Accelerator / Incubator", r"\baccelerator|incubator\b"),
        ("Referral / Talent Network", r"\breferral|early talent|talent network|talent community\b"),
    ]
    for label, pattern in categories:
        if re.search(pattern, text, re.I):
            return label
    return "Other Opportunity"

def extract_roles(text):
    return ", ".join(
        label for label, pattern in ROLE_PATTERNS if re.search(pattern, text, re.I)
    )

def extract_season(text):
    matches = re.findall(r"\b(Summer|Fall|Autumn|Winter|Spring)\s+(20\d{2})\b", text, re.I)
    if matches:
        return ", ".join(dict.fromkeys(f"{season.title()} {year}" for season, year in matches))
    years = re.findall(r"\b20(?:2[6-9]|3\d)\b", text)
    return ", ".join(dict.fromkeys(years))

def extract_location(text):
    places = [
        "Seattle", "Kirkland", "Bellevue", "Redmond", "San Francisco", "Bay Area",
        "New York", "NYC", "Austin", "Boston", "Chicago", "Los Angeles", "Sunnyvale",
        "Mountain View", "Menlo Park", "Washington, DC", "Washington DC", "Remote"
    ]
    found = [place for place in places if re.search(rf"\b{re.escape(place)}\b", text, re.I)]
    return ", ".join(dict.fromkeys(found))

def extract_deadline(text):
    patterns = [
        r"(?:deadline|due|apply by|register by)\s*[:\-]?\s*([A-Z][a-z]{2,8}\.?\s+\d{1,2}(?:,\s*20\d{2})?)",
        r"(?:deadline|due|apply by|register by)\s*[:\-]?\s*(\d{1,2}/\d{1,2}(?:/20\d{2})?)",
        r"(?:deadline|due|apply by|register by)\s*[:\-]?\s*(20\d{2}-\d{2}-\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1).strip()
    return ""

def extract_status(text):
    if re.search(r"\bclosed|deadline passed|no longer accepting|filled\b", text, re.I):
        return "Closed"
    if re.search(r"\breopen|re-open\b", text, re.I):
        return "Reopened"
    if re.search(r"\bopen(?:ed)?|apply now|applications? (?:are )?live|registration (?:is )?open\b", text, re.I):
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

def _line_quality(line):
    line = re.sub(r"https?://\\S+", "", line).strip(" •|-—_")
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

def opportunity_title(org, category, role, text):
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("http"):
            continue
        score = _line_quality(line)
        if score >= 0:
            lines.append((score, line))

    best_line = max(lines, default=(0, ""))[1][:100]
    if org and role:
        return f"{org} — {role}"
    if org:
        return f"{org} — {category}"
    if (
        best_line
        and OPPORTUNITY_RE.search(best_line)
        and not NEGATIVE_CONTEXT_RE.search(best_line)
        and not best_line.startswith(("-", "(", "|"))
        and not best_line.endswith(("?", "&", ",", "|"))
    ):
        return best_line
    return role or category

def normalize_identity_text(value):
    value = URL_RE.sub(" ", value or "")
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return " ".join(value.split())

def instagram_media_key(links):
    for url in links:
        try:
            parsed = urlparse(url)
            params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            if params.get("ig_cache_key"):
                return params["ig_cache_key"]
            if is_media_url(url):
                filename = Path(parsed.path).name
                if filename:
                    return filename
        except Exception:
            continue
    return ""

def stable_item_key(item):
    for key in (
        "id", "pk", "story_pk", "story_id", "storyId", "media_id", "mediaId",
        "shortCode", "shortcode",
    ):
        value = item.get(key)
        if value not in (None, ""):
            return f"{key.lower()}:{value}"
    return ""

def row_id(item, source_type, category, role, links, text):
    stable = stable_item_key(item)
    media = instagram_media_key(links)
    ex = external_links(links)
    if stable:
        basis = f"{source_type}:{stable}"
    elif media:
        basis = f"{source_type}:media:{media}"
    elif ex:
        basis = f"link:{clean_url(ex[0])}|{normalize_identity_text(opportunity_title('', category, role, text))}"
    else:
        basis = (
            f"{source_type}:{posted_at(item)}:"
            f"{normalize_identity_text(text)[:1000]}"
        )
    return hashlib.sha256(basis.encode("utf-8", errors="ignore")).hexdigest()[:20]

def normalize_item(item, source_type):
    text = item_text(item)
    links = normalize_links(item)
    if not looks_actionable(text, links):
        return None

    org = extract_organization(text, links)
    category = extract_category(text)
    role = extract_roles(text)
    ex = external_links(links)
    destination = ex[0] if ex else ""

    return {
        "ID": row_id(item, source_type, category, role, links, text),
        "First Seen": datetime.now(timezone.utc).isoformat(),
        "Posted At": posted_at(item),
        "Organization": org,
        "Opportunity": opportunity_title(org, category, role, text),
        "Category": category,
        "Role / Track": role,
        "Season / Year": extract_season(text),
        "Location": extract_location(text),
        "Deadline": extract_deadline(text),
        "Application / Registration Link": destination,
        "Instagram Source": source_url(item, source_type),
        "Source Type": source_type,
        "Raw Text": text[:12000],
        "Status": extract_status(text),
        "Priority": "",
        "Actioned?": "No",
        "Notes": "",
    }

def create_workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Opportunities"
    ws.append(HEADERS)

    header_fill = PatternFill("solid", fgColor="17365D")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    widths = [20, 22, 22, 20, 34, 24, 24, 18, 18, 18, 40, 40, 16, 60, 14, 14, 14, 28]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = "A1:R1"

    dashboard = wb.create_sheet("Dashboard")
    dashboard["A1"] = "Zero2Sudo Opportunity Monitor"
    dashboard["A1"].font = Font(size=18, bold=True, color="FFFFFF")
    dashboard["A1"].fill = header_fill
    dashboard.merge_cells("A1:D1")

    metrics = [
        ("Total opportunities", '=COUNTA(Opportunities!A2:A5000)'),
        ("Open / reopened", '=COUNTIF(Opportunities!O2:O5000,"Open")+COUNTIF(Opportunities!O2:O5000,"Reopened")'),
        ("Not actioned", '=COUNTIF(Opportunities!Q2:Q5000,"No")'),
        ("Actioned", '=COUNTIF(Opportunities!Q2:Q5000,"Yes")'),
        ("Internships", '=COUNTIF(Opportunities!F2:F5000,"Internship")'),
        ("Fellowships", '=COUNTIF(Opportunities!F2:F5000,"Fellowship")'),
        ("Scholarships / grants", '=COUNTIF(Opportunities!F2:F5000,"Scholarship / Grant")'),
    ]
    dashboard.append([])
    dashboard.append(["Metric", "Value"])
    for name, formula in metrics:
        dashboard.append([name, formula])
    dashboard.column_dimensions["A"].width = 28
    dashboard.column_dimensions["B"].width = 18

    wb.save(path)

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

def merge_record(target, source):
    merged = dict(target)
    for header in HEADERS:
        if header in {"Actioned?", "Notes"}:
            continue
        if merged.get(header) in (None, "") and source.get(header) not in (None, ""):
            merged[header] = source[header]
    if str(source.get("Actioned?", "")).strip().lower() == "yes":
        merged["Actioned?"] = "Yes"
    notes = []
    for value in (target.get("Notes"), source.get("Notes")):
        value = str(value or "").strip()
        if value and value not in notes:
            notes.append(value)
    merged["Notes"] = " | ".join(notes)
    return merged

def conservative_record_title(record):
    organization = str(record.get("Organization") or "").strip()
    role = str(record.get("Role / Track") or "").strip()
    category = str(record.get("Category") or "Opportunity").strip()
    current = str(record.get("Opportunity") or "").strip()
    if organization:
        return f"{organization} — {role or category}"
    low_quality = (
        not current
        or len(current) > 100
        or current.startswith(("-", "(", "@", "|"))
        or current.endswith(("?", "&", ",", "|"))
        or bool(NEGATIVE_CONTEXT_RE.search(current))
        or bool(re.search(
            r"\b(if you|as an|all intern roles|posted today|please fill out|"
            r"been the driving|has anyone|this is why)\b",
            current,
            re.I,
        ))
    )
    return (role or category) if low_quality else current

def cleanup_records(records):
    cleaned = []
    index_by_key = {}
    invalid_links_cleared = 0
    duplicates_removed = 0
    for original in records:
        record = {header: original.get(header, "") for header in HEADERS}
        application = record.get("Application / Registration Link", "") or ""
        if application:
            valid_external = external_links([application])
            if not valid_external:
                record["Application / Registration Link"] = ""
                invalid_links_cleared += 1
            else:
                record["Application / Registration Link"] = valid_external[0]
        record["Opportunity"] = conservative_record_title(record)
        key = record_semantic_key(record)
        record["ID"] = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        if key in index_by_key:
            position = index_by_key[key]
            cleaned[position] = merge_record(cleaned[position], record)
            duplicates_removed += 1
        else:
            index_by_key[key] = len(cleaned)
            cleaned.append(record)
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
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.save(TRACKER_PATH)

def migrate_workbook():
    records = workbook_records()
    cleaned, stats = cleanup_records(records)
    changed = cleaned != records
    if changed:
        save_records(cleaned)
    stats.update({"before": len(records), "after": len(cleaned), "changed": changed})
    return stats

def apply_manual_fields(records, manual_fields):
    for record in records:
        values = manual_fields.get(str(record.get("ID", "")), {})
        if values.get("Actioned?") not in (None, ""):
            record["Actioned?"] = values["Actioned?"]
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
    wb = load_workbook(TRACKER_PATH)
    ws = wb["Opportunities"]
    for record in rows:
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
    ws.auto_filter.ref = f"A1:R{ws.max_row}"
    wb.save(TRACKER_PATH)

def tracker_url():
    if GOOGLE_SHEET_ID:
        return f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit"
    if GITHUB_REPOSITORY:
        return f"https://github.com/{GITHUB_REPOSITORY}/blob/main/{LIVE_VIEW_PATH.name}"
    return str(LIVE_VIEW_PATH)

def write_live_view(records):
    rows = sorted(
        records,
        key=lambda row: str(row.get("First Seen", "") or ""),
        reverse=True,
    )
    lines = [
        "# Zero2Sudo Opportunity Tracker",
        "",
        f"Last updated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "This page updates automatically. The Excel workbook remains available as a backup.",
        "",
        "| Opportunity | Category | Status | Priority | Link |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        title = str(row.get("Opportunity") or row.get("Category") or "Opportunity").replace("|", "\\|")
        category = str(row.get("Category") or "").replace("|", "\\|")
        status = str(row.get("Status") or "").replace("|", "\\|")
        priority = str(row.get("Priority") or "").replace("|", "\\|")
        application = row.get("Application / Registration Link") or ""
        source = row.get("Instagram Source") or ""
        if application:
            link = f"[Apply / Register]({application})"
        elif source:
            link = f"[View Instagram source]({source})"
        else:
            link = "—"
        lines.append(f"| {title} | {category} | {status} | {priority} | {link} |")
    LIVE_VIEW_PATH.write_text("\n".join(lines) + "\n")

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

def priority_for(row):
    organization = row.get("Organization", "")
    text = " ".join([
        organization,
        row.get("Opportunity", ""),
        row.get("Category", ""),
        row.get("Role / Track", ""),
    ])

    high_org_re = re.compile(
        r"\b(palantir|anduril|scale ai|primer|vannevar|shield ai|"
        r"openai|anthropic|databricks)\b",
        re.I,
    )
    preferred_re = re.compile(
        r"\b(software engineering|machine learning|artificial intelligence|"
        r"ai|data engineering|data science|new grad|internship)\b",
        re.I,
    )

    if high_org_re.search(organization):
        return "HIGH"
    if preferred_re.search(text):
        return "MEDIUM"
    return "NORMAL"

def clean_alert_title(row):
    org = row.get("Organization") or ""
    opp = row.get("Opportunity") or row.get("Category") or "New opportunity"
    if org and not opp.lower().startswith(org.lower()):
        return f"{org} — {opp}"
    return opp

def ntfy_alert(rows, batch_id=""):
    if not rows or not NTFY_TOPIC:
        return True

    ranked = sorted(rows, key=lambda r: {"HIGH": 0, "MEDIUM": 1, "NORMAL": 2}[priority_for(r)])
    top = ranked[0]
    priority = priority_for(top)
    title = clean_alert_title(top)

    prefix = "🚨" if priority == "HIGH" else "📣"
    ntfy_title = f"{prefix} {priority}: {title}"

    body_lines = []
    for row in ranked[:5]:
        p = priority_for(row)
        label = clean_alert_title(row)
        deadline = row.get("Deadline") or ""
        link = row.get("Application / Registration Link") or row.get("Instagram Source") or ""
        meta = " · ".join(x for x in [row.get("Category", ""), deadline] if x)
        body_lines.append(f"[{p}] {label}" + (f" — {meta}" if meta else ""))
        if link:
            body_lines.append(link)
        body_lines.append("")

    if len(ranked) > 5:
        body_lines.append(f"+ {len(ranked) - 5} more in the tracker")

    headers = {
        "Title": ntfy_title[:150],
        "Tags": "rotating_light,briefcase" if priority == "HIGH" else "briefcase",
        "Priority": "5" if priority == "HIGH" else ("4" if priority == "MEDIUM" else "3"),
    }
    if batch_id:
        headers["X-Message-ID"] = f"zero2sudo-{batch_id}"

    top_link = top.get("Application / Registration Link") or top.get("Instagram Source") or ""
    if top_link:
        headers["Click"] = top_link
        headers["Actions"] = f"view, Apply / Open, {top_link}, clear=true"

    response = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data="\n".join(body_lines).strip().encode("utf-8"),
        headers=headers,
        timeout=30,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"ntfy push failed with status {response.status_code}.")
    print("Sent ntfy push notification.")
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

    lines = [
        marker,
        f"@{owner}",
        "",
        f"Zero2Sudo shared **{len(rows)} new actionable opportunit{'y' if len(rows) == 1 else 'ies'}**.",
        "",
        "| Opportunity | Category | Deadline | Link |",
        "|---|---|---|---|",
    ]
    for row in rows[:20]:
        title = row["Opportunity"].replace("|", "\\|")
        category = row["Category"].replace("|", "\\|")
        deadline = (row["Deadline"] or "—").replace("|", "\\|")
        link = row["Application / Registration Link"] or row["Instagram Source"]
        lines.append(f"| {title} | {category} | {deadline} | [Open]({link}) |")

    if len(rows) > 20:
        lines.extend(["", f"_Plus {len(rows) - 20} more in the Excel tracker._"])

    lines.extend([
        "",
        f"Live tracker: [Open the current tracker]({tracker_url()})",
        "",
        f"Excel backup: [Download workbook](https://github.com/{GITHUB_REPOSITORY}/blob/main/{TRACKER_PATH.name})",
        "",
        "_Created automatically by the hourly Zero2Sudo monitor._",
    ])

    noun = "opportunity" if len(rows) == 1 else "opportunities"
    ranked = sorted(rows, key=lambda r: {"HIGH": 0, "MEDIUM": 1, "NORMAL": 2}[priority_for(r)])
    top = ranked[0]
    top_priority = priority_for(top)
    top_title = clean_alert_title(top)
    prefix = "🚨" if top_priority == "HIGH" else "📣"
    if len(rows) == 1:
        title = f"{prefix} [{top_priority}] {top_title} — APPLY / OPEN"
    else:
        title = f"{prefix} [{top_priority}] {top_title} + {len(rows) - 1} more"
    payload = {"title": title, "body": "\n".join(lines), "assignees": [owner]}
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
    )
    if merged != records:
        save_records(merged)
        write_live_view(merged)
    print(f"Verified {len(merged)} rows in Google Sheets.")
    return True

def main(defer_notifications=False):
    if not APIFY_TOKEN:
        raise SystemExit(
            "APIFY_TOKEN is missing. Add it in GitHub: Settings → Secrets and variables → Actions → New repository secret."
        )

    ensure_workbook()
    cleanup = migrate_workbook()
    records = workbook_records()
    manual_fields = pull_google_manual_fields()
    if manual_fields:
        before_manual = [dict(record) for record in records]
        updated = apply_manual_fields(records, manual_fields)
        if updated != before_manual:
            save_records(updated)
        records = updated
    known_ids = {str(record.get("ID")) for record in records if record.get("ID")}
    known_keys = {record_semantic_key(record) for record in records}

    candidates = []
    for item in fetch_stories():
        record = normalize_item(item, "Story")
        if record:
            candidates.append(record)
    for item in fetch_posts():
        record = normalize_item(item, "Post / Reel")
        if record:
            candidates.append(record)

    # Deduplicate by stable source/content identity, not temporary CDN URLs.
    unique = {}
    for record in candidates:
        unique.setdefault(record_semantic_key(record), record)
    new_rows = [record for key, record in unique.items() if key not in known_keys]

    # Fill the spreadsheet Priority column automatically for new rows.
    for row in new_rows:
        row["Priority"] = priority_for(row).title()

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
    }
    STATUS_PATH.write_text(json.dumps(report, indent=2) + "\n")
    if not defer_notifications:
        sync_google_sheet()
        deliver_pending_batches()
    print(f"Added {len(new_rows)} new opportunity row(s).")
    print(f"Verified {len(persisted)} total rows in {TRACKER_PATH}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--defer-notifications", action="store_true")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--sync-google", action="store_true")
    args = parser.parse_args()
    if args.notify:
        deliver_pending_batches()
    elif args.sync_google:
        sync_google_sheet()
    else:
        main(defer_notifications=args.defer_notifications)
