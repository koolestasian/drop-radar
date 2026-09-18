#!/usr/bin/env python3
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

STORY_ACTOR = os.getenv("STORY_ACTOR", "data-slayer/instagram-stories-scraper")
POST_ACTOR = os.getenv("POST_ACTOR", "apify/instagram-scraper")

GITHUB_TOKEN = os.getenv("GH_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()

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
    return data if isinstance(data, list) else []

def fetch_stories():
    try:
        return run_actor(STORY_ACTOR, {"usernames": [USERNAME]})
    except Exception as exc:
        print(f"::warning::Story scrape failed: {exc}")
        return []

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
        print(f"::warning::Post/reel scrape failed: {exc}")
        return []

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

def normalize_links(item):
    found = []
    for key in (
        "link_urls", "links", "url", "externalUrl", "external_url",
        "postUrl", "post_url", "linkUrl", "link_url"
    ):
        value = item.get(key)
        if isinstance(value, str) and value.startswith("http"):
            found.append(value)
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, str) and entry.startswith("http"):
                    found.append(entry)
                elif isinstance(entry, dict):
                    for subkey in ("url", "href", "link", "link_url", "linkUrl"):
                        url = entry.get(subkey)
                        if isinstance(url, str) and url.startswith("http"):
                            found.append(url)
    return list(dict.fromkeys(found))

def is_instagram_url(url):
    try:
        return "instagram.com" in urlparse(url).netloc.lower()
    except Exception:
        return False

def external_links(links):
    return [url for url in links if not is_instagram_url(url)]

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
    if OPPORTUNITY_RE.search(text):
        if NOISE_RE.search(text) and not ACTION_RE.search(text) and not external_links(links):
            return False
        return True
    # Bias toward recall: an external destination plus an action verb is worth surfacing.
    if external_links(links) and ACTION_RE.search(text):
        return True
    return False

def organization_from_links(links):
    for url in external_links(links):
        try:
            host = urlparse(url).netloc.lower().removeprefix("www.")
            for domain, organization in DOMAIN_ORGS.items():
                if host == domain or host.endswith("." + domain):
                    return organization
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
        if isinstance(value, str) and value.startswith("http"):
            return value
    shortcode = pick(item, "shortCode", "shortcode")
    if shortcode:
        return f"https://www.instagram.com/p/{shortcode}/"
    if source_type == "Story":
        return f"https://www.instagram.com/stories/{USERNAME}/"
    return f"https://www.instagram.com/{USERNAME}/"

def opportunity_title(org, category, role, text):
    if org and role:
        return f"{org} — {role}"
    if org:
        return f"{org} — {category}"
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("http"):
            return line[:140]
    return category

def row_id(item, source_type, category, role, links, text):
    ex = external_links(links)
    if ex:
        basis = f"link:{clean_url(ex[0])}|{category}|{role}"
    else:
        stable = pick(item, "id", "pk", "story_pk", "shortCode", "shortcode")
        basis = f"{source_type}:{stable or posted_at(item)}:{text[:500]}"
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
    destination = ex[0] if ex else (links[0] if links else "")

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

def github_issue(rows):
    if not rows or not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        return

    owner = GITHUB_REPOSITORY.split("/", 1)[0]
    lines = [
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
        f"Tracker: [Zero2Sudo_Opportunity_Tracker.xlsx](https://github.com/{GITHUB_REPOSITORY}/blob/main/{TRACKER_PATH.name})",
        "",
        "_Created automatically by the hourly Zero2Sudo monitor._",
    ])

    noun = "opportunity" if len(rows) == 1 else "opportunities"
    title = f"Zero2Sudo: {len(rows)} new {noun} — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    issue_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues"
    payload = {"title": title, "body": "\n".join(lines), "assignees": [owner]}
    response = requests.post(issue_url, headers=headers, json=payload, timeout=30)

    # Some repository permission combinations reject assignment. The @mention in
    # the body still alerts the owner, so retry without assignees rather than
    # losing the alert entirely.
    if response.status_code == 422:
        payload.pop("assignees", None)
        response = requests.post(issue_url, headers=headers, json=payload, timeout=30)

    if response.status_code >= 300:
        print(f"::warning::Could not create GitHub alert issue: {response.status_code} {response.text}")
    else:
        print(f"Created alert issue: {response.json().get('html_url', '')}")

def main():
    if not APIFY_TOKEN:
        raise SystemExit(
            "APIFY_TOKEN is missing. Add it in GitHub: Settings → Secrets and variables → Actions → New repository secret."
        )

    ensure_workbook()
    known = existing_ids()

    candidates = []
    for item in fetch_stories():
        record = normalize_item(item, "Story")
        if record:
            candidates.append(record)
    for item in fetch_posts():
        record = normalize_item(item, "Post / Reel")
        if record:
            candidates.append(record)

    # Deduplicate within this run and against the workbook.
    unique = {record["ID"]: record for record in candidates}
    new_rows = [record for key, record in unique.items() if key not in known]

    if not new_rows:
        print("No new actionable opportunities.")
        return

    append_rows(new_rows)
    github_issue(new_rows)
    print(f"Added {len(new_rows)} new opportunity row(s).")

if __name__ == "__main__":
    main()
