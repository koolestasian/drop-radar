import json, os, urllib.request, urllib.error, urllib.parse, time
tok = os.environ["API_TOKENS"].split(",")[0].split(":", 1)[1]
def t(**p):
    req = urllib.request.Request("http://127.0.0.1:8000/api/opportunities?" + urllib.parse.urlencode({"limit": 30, "sort": "posted", **p}), headers={"Authorization": "Bearer " + tok})
    s = time.time(); n = len(json.load(urllib.request.urlopen(req, timeout=180))["items"]); return n, round(time.time() - s, 2)
for name, p in [("you", dict(include="matches")), ("you level=intern", dict(include="matches", level="intern")),
  ("you track=Quant", dict(include="matches", track="Quant")), ("you posted=1", dict(include="matches", posted_within=1)),
  ("you posted=7", dict(include="matches", posted_within=7)), ("you prestige", dict(include="matches", sort="prestige")),
  ("you us_only", dict(include="matches", us_only="true")), ("you location", dict(include="matches", location="new york")),
  ("all track=Quant", dict(include="all", track="Quant")), ("all level=new_grad", dict(include="all", level="new_grad")),
  ("all posted=1", dict(include="all", posted_within=1)), ("you new=1", dict(include="matches", backfill="false", since="2026-10-03T00:00:00Z"))]:
    print(name, t(**p))
