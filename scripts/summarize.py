#!/usr/bin/env python3
import json, statistics as st, csv, collections
rows = [json.loads(l) for l in open("results/raw.jsonl")]
g = collections.defaultdict(list)
for r in rows:
    g[(r["rtt"], r["mode"])].append(r)

def ms(vals):
    return st.mean(vals), (st.stdev(vals) if len(vals) > 1 else 0.0)

def fmt(vals, d=3):
    m, s = ms(vals)
    return f"{m:.{d}f} ± {s:.{d}f}"

out = []
hdr = ["RTT(ms)", "Mode", "Page time (s)", "Page TCP conns", "Load req/s", "Load mean latency (ms)", "Load TCP conns", "Failures"]
print("| " + " | ".join(hdr) + " |")
print("|" + "---|" * len(hdr))
for (rtt, mode) in sorted(g):
    rs = g[(rtt, mode)]
    pt = [r["page"]["time_s"] for r in rs]
    pc = [r["page"]["tcp_conns"] for r in rs]
    rps = [r["load"]["req_per_s"] for r in rs]
    lat = [r["load"]["mean_lat_ms"] for r in rs]
    lc = [r["load"]["tcp_conns"] for r in rs]
    fl = sum(r["page"]["failures"] + r["load"]["failures"] for r in rs)
    row = [rtt, mode, fmt(pt), fmt(pc, 1), fmt(rps, 1), fmt(lat, 1), fmt(lc, 1), fl]
    out.append(row)
    print("| " + " | ".join(map(str, row)) + " |")

print("\nMode C phases and cache statistics")
h2 = ["RTT(ms)", "Cold (s)", "Warm (s)", "Stale (s)", "Hit ratio", "Upstream reqs / 300", "Reval 304"]
print("| " + " | ".join(h2) + " |")
print("|" + "---|" * len(h2))
out2 = []
for rtt in (20, 100, 200):
    rs = g[(rtt, "C")]
    row = [rtt,
           fmt([r["cold"]["time_s"] for r in rs]),
           fmt([r["warm"]["time_s"] for r in rs]),
           fmt([r["stale"]["time_s"] for r in rs]),
           fmt([r["proxy_stats"]["hit_ratio"] for r in rs], 3),
           fmt([r["proxy_stats"]["upstream_requests"] for r in rs], 1),
           fmt([r["proxy_stats"]["reval_304"] for r in rs], 1)]
    out2.append(row)
    print("| " + " | ".join(map(str, row)) + " |")

with open("results/summary.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(hdr); w.writerows(out)
    w.writerow([]); w.writerow(h2); w.writerows(out2)
print("\nsaved results/summary.csv")
