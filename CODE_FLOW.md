# Code flow and demo guide (Project 20)

## Components
| File | Role |
|---|---|
| topo.clab.yml | Creates 6 nodes from image cn-lab, bind-mounts src, www and captures, assigns IPs and static routes via exec, enables ip_forward on r1/r2, builds bridge br0 on sw (eth1 client, eth2 proxy, eth3 r1) |
| src/server.py | Origin on :8080. main() accepts TCP connections and submits each to a thread pool; handle() loops over requests on that connection |
| src/proxy.py | Caching proxy on :8888. main() -> handle() per client connection -> serve_get() cache logic -> Upstream (persistent connection to origin) -> respond() adds X-Cache, Age, Via |
| src/client.py | Raw-socket measurement client. Modes A (direct, Connection: close), B (direct, persistent), C (persistent via proxy) |
| scripts/set_rtt.sh | netem delay (RTT/2 per side) plus tbf 10 Mbit/s on R1 eth2 and R2 eth1; disables tso/gso/gro |
| scripts/run_experiments.sh | 3 RTTs x 3 runs x modes A,B,C; calls client.py; tags JSON with rtt and run; appends to results/raw.jsonl |
| scripts/summarize.py | Groups raw.jsonl by (rtt, mode), mean +/- sd, writes results/summary.csv |
| scripts/run_ab.sh | 18 ApacheBench runs (HTTP/1.0, with/without -k) -> results/ab_raw.csv |
| dashboard/ | Express app serving results/*.csv as JSON plus a static page; not on the measured path |

Data flow: topo.clab.yml builds the network, set_rtt.sh shapes it, run_experiments.sh runs client.py in the client container,
client.py -> raw.jsonl -> summarize.py -> summary.csv -> dashboard.

## server.py: one connection
1. Set TCP_NODELAY and an idle timeout (15 s). Read the request line (3 parts, else 400), then headers until the blank line, lower-casing names.
2. Read Content-Length bytes as the body.
3. Keep-alive rule: HTTP/1.1 keeps the connection unless "Connection: close"; HTTP/1.0 keeps it only with "Connection: keep-alive".
4. Route: POST /echo returns the body (200). Methods other than GET/HEAD/POST give 405. /old-page gives 301 with Location.
   Otherwise map the URL to a file under /www (realpath check blocks path traversal). A missing file, or POST elsewhere, gives 404.
   /noetag/<file> serves the same file without an ETag, to exercise If-Modified-Since.
5. For a file: build ETag and Last-Modified, call not_modified() (If-None-Match wins over If-Modified-Since). 304 has no body; otherwise 200 with Content-Length. HEAD sends headers only.
6. Loop for the next request on the same socket until close or idle timeout. Every request is logged.

## proxy.py: serve_get()
1. If the client sent its own validators: BYPASS, forward upstream, pass the answer (including 304) back.
2. If cached and age < max-age: HIT, answered from memory with Age; origin sees nothing. Stored headers are replayed, so Date is the original one.
3. If cached but stale: revalidate with If-None-Match (or If-Modified-Since if no ETag, else unconditional).
   304 -> refresh stored time, serve cached body as 200 (X-Cache: REVALIDATED-304).
   200 -> replace entry (REVALIDATED-CHANGED). Non-200 -> drop entry.
4. Not cached: MISS, fetch upstream, store only if status 200 and max-age > 0.
5. HEAD, POST and other methods bypass the cache. CACHE is a dict guarded by LOCK; STATS counters are served at /__stats; /__reset clears both.
6. Limitation: no request coalescing (two concurrent misses both go upstream).

## client.py: one run
- Page bundle: index.html plus 20 objects over 5 parallel connections (A opens a new connection per object, 21 in total; B and C reuse 5).
- Load test: 300 requests at concurrency 5 over 21 paths, counting TCP connections.
- Mode C: reset, cold page, warm page, sleep 11 s, stale page, reset, cold page for comparison with A/B, reset, then the load test; finally reads /__stats.
- Prints one JSON line.

## Demo script (about 10 minutes)
1. architecture.png; ip route on r1; traceroute -n 10.10.3.10 (the 20 ms jump at hop 2 is the netem delay).
2. cat scripts/set_rtt.sh; ping showing about 21 ms.
3. README section 4: 200, 301, 404, HEAD, POST.
4. Wireshark: 01_connection_reuse (1 SYN) vs 02_connection_close (3 SYNs).
5. Proxy: __reset, MISS, HIT, __stats; then /noetag/ with a 12 s wait for REVALIDATED-304; open 10b to show If-Modified-Since.
6. 04b: conditional GET answered by a 281 B 304 instead of a 2533 B 200.
7. Dashboard at localhost:3000; quote the 100 ms row: page A 1.068 s, B 0.745 s, C 0.745 s, warm cache 0.04 s; load req/s A 24, B 47, C 365; ab 23.7 vs 46.1.
8. Code tour: handle() in server.py, serve_get() in proxy.py, fetch_page() in client.py.

## Likely questions
- Why does client-proxy traffic never cross R1? Same subnet and bridge sw: switched at layer 2. Hence capture on proxy eth1.
- Why is mode A about 10 RTT per page at 100 ms? About 2 RTT per object (handshake plus request), 21 objects over 5 connections.
- Why is B not twice as fast as A? Handshakes vanish, but transferring about 262 KB at 10 Mbit/s still takes about 0.2 s.
- Why does revalidation save bytes but not time? The 304 still costs one round trip to the origin; only the response shrinks.
- Why is mode C req/s so high? Cache hits (ratio about 0.92) are answered locally, not a faster server.
- ETag vs Last-Modified? ETag is a content validator and takes precedence; Last-Modified has 1 s granularity and is the fallback (/noetag/).
- tbf bug? burst 32kbit was smaller than TSO/GSO packets on the veth, so transfers stalled. Fixed by disabling offloads and burst 100kb.
- Is ApacheBench proof of HTTP/1.1 persistence? No: it sends HTTP/1.0 and opts into keep-alive; it shows the effect only.
- Validity on one laptop? Separate namespaces with real kernel routing and shaping, but one shared CPU; we compare trends and report spread over 3 runs.
