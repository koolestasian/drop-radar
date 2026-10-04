# runs on the box: pages the live API (read-only) and prints one JSON line per row; the token is never printed
import json, os, sys, urllib.request, urllib.parse
tok = os.environ["API_TOKENS"].split(",")[0].split(":", 1)[1]
include = sys.argv[1]
cursor = None
while True:
    q = {"include": include, "limit": 200, **({"cursor": cursor} if cursor else {})}
    req = urllib.request.Request("http://127.0.0.1:8000/api/opportunities?" + urllib.parse.urlencode(q), headers={"Authorization": "Bearer " + tok})
    page = json.load(urllib.request.urlopen(req, timeout=120))
    for o in page["items"]:
        print(json.dumps({k: o[k] for k in ("id", "title", "category", "role_track", "published_at", "first_seen", "backfill", "level", "track")}))
    cursor = page["next_cursor"]
    if not cursor:
        break
