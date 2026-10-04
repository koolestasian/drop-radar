import json, sys, time, bisect, random
sys.path.insert(0, ".")
from radar.pipeline.roles import level, track, TRACK_NAMES
S = sys.argv[1]
rows = [json.loads(l) for l in open(f"{S}/all.jsonl")]
you = {json.loads(l)["id"] for l in open(f"{S}/matches.jsonl")}
key = lambda r: r["published_at"] or ("" if r["backfill"] else r["first_seen"])
t = time.perf_counter()
rows.sort(key=lambda r: (key(r), r["id"]))          # oldest first: bit i = rank i, newest = highest bit
keys = [key(r) for r in rows]
bits = {}
def add(name, i): bits[name] = bits.get(name, 0) | (1 << i)
for i, r in enumerate(rows):
    if r["id"] in you: add("you", i)
    lv = level(r["title"], r["category"]); add("level:" + (lv or "other"), i)
    add("track:" + track(r["title"], r["role_track"]), i)
    if not r["backfill"]: add("drops", i)
build = time.perf_counter() - t
ALL = (1 << len(rows)) - 1
def page(mask, k=30):
    out = []
    while mask and len(out) < k:
        i = mask.bit_length() - 1      # newest remaining
        out.append(i); mask ^= 1 << i
    return out
def since(day):                         # posted_within: a prefix of the order, found by binary search
    return ALL ^ ((1 << bisect.bisect_left(keys, day)) - 1)
def bench(name, f, n=200):
    t = time.perf_counter()
    for _ in range(n): r = f()
    print(f"{name:45s} {(time.perf_counter() - t) / n * 1e6:9.1f} us   -> {len(r) if isinstance(r, list) else r}")
print(f"rows {len(rows)}  build {build*1000:.0f} ms (pure Python, incl. regex classify)")
bench("For you, first 30", lambda: page(bits["you"]))
bench("For you & intern & Software, first 30", lambda: page(bits["you"] & bits["level:intern"] & bits["track:Software"]))
bench("For you & Quant (rare, 7 hits)", lambda: page(bits["you"] & bits["track:Quant"]))
bench("Everything & posted 7d & new grad", lambda: page(since("2026-09-27") & bits["level:new_grad"]))
bench("For you drops only", lambda: page(bits["you"] & bits["drops"]))
bench("count For you (popcount)", lambda: bits["you"].bit_count())
bench("all pill counts, both scopes (2x12 popcounts)", lambda: [(m & bits[n]).bit_count() for m in (bits["you"], ALL) for n in bits if n.startswith(("level:", "track:"))])
bench("page 10 (rows 271-300) of For you", lambda: page(bits["you"], 300)[270:])
print("bitset size bytes", (bits["you"].bit_length() + 7) // 8)
