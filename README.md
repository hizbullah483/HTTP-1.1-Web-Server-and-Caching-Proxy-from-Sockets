# Project 20: HTTP/1.1 Web Server and Caching Proxy from Sockets

CS3001 Computer Networks, Fall 2026.
Mubashir Sikandar (24K-1038), Muhammad Hizbullah (24K-1001), Fazeel Tariq (24K-0919).

A raw-socket HTTP/1.1 origin server and caching proxy (Python 3 standard library only), deployed on a routed
containerlab topology (3 subnets, 2 routers, static routes). Experiments compare (A) direct with
`Connection: close`, (B) direct persistent, and (C) persistent through the caching proxy at 20, 100 and 200 ms RTT.

## Requirements
- Windows with WSL2 (Ubuntu), or native Ubuntu 22.04/24.04
- Docker Engine, containerlab (tested with 0.79.0), Wireshark (on the host, to open .pcapng files)
- Python 3 with matplotlib on the host (only for the diagram script)
- No cloud account, API key or paid service is needed.

## Folder layout
| Path | Purpose |
|---|---|
| `Dockerfile` | Image `cn-lab` (Ubuntu 24.04: python3, iproute2, tcpdump, tshark, curl, apache2-utils, ethtool) |
| `topo.clab.yml` | containerlab topology: client, proxy, sw, r1, r2, origin |
| `src/server.py` | Origin server: GET, HEAD, POST /echo, 200/301/304/404/405, keep-alive, ETag and Last-Modified |
| `src/proxy.py` | Caching proxy: fresh hits, ETag / If-Modified-Since revalidation, /__stats, /__reset |
| `src/client.py` | Measurement client (modes A, B, C), prints JSON |
| `www/` | Test site: index.html with 20 embedded objects, new-page.html |
| `scripts/set_rtt.sh` | Applies netem delay and tbf 10 Mbit/s on the R1-R2 link |
| `scripts/run_experiments.sh` | The 27 main runs (3 RTTs x 3 runs x modes A, B, C) |
| `scripts/run_ab.sh` | 18 supplementary ApacheBench runs (HTTP/1.0, with and without -k) |
| `scripts/summarize.py` | Builds `results/summary.csv` from `results/raw.jsonl` |
| `scripts/make_diagram.py` | Generates `diagram/architecture.png` |
| `dashboard/` | Express dashboard (read-only view of `results/`) |
| `captures/` | Saved .pcapng traces and server logs |
| `results/` | raw.jsonl, summary.csv, ab_raw.csv, ab_summary.csv |

## Addressing plan
| Subnet | Nodes |
|---|---|
| 10.10.1.0/24 client LAN | client 10.10.1.10, proxy 10.10.1.20:8888, R1 eth1 10.10.1.1 (gateway) |
| 10.10.2.0/24 transit | R1 eth2 10.10.2.1, R2 eth1 10.10.2.2 |
| 10.10.3.0/24 server LAN | R2 eth2 10.10.3.1 (gateway), origin 10.10.3.10:8080 |

`sw` is a Linux bridge (br0) joining client, proxy and R1. Links: client-sw, proxy-sw, sw-r1, r1-r2, r2-origin.
Nodes are Linux network namespaces created by containerlab. Static routes and IP forwarding are set on R1 and R2.

## 1. Build and deploy
```
docker build -t cn-lab:latest .
sudo containerlab deploy -t topo.clab.yml
```
To redeploy from scratch: `sudo containerlab destroy -t topo.clab.yml --cleanup` first.
If Docker is not running (WSL): `sudo service docker start`.

## 2. Start the services (required after every deploy)
```
docker exec -d clab-http20-origin sh -c "python3 -u /app/server.py > /captures/origin.log 2>&1"
docker exec -d clab-http20-proxy sh -c "python3 -u /app/proxy.py > /captures/proxy.log 2>&1"
./scripts/set_rtt.sh 20
```
`./src`, `./www` and `./captures` are bind-mounted into the containers as `/app`, `/www` and `/captures`.

## 3. Verify the routed baseline
```
docker exec clab-http20-client ip route
docker exec clab-http20-r1 ip route
docker exec clab-http20-r2 ip route
docker exec clab-http20-client traceroute -n 10.10.3.10
docker exec clab-http20-client ping -c 3 10.10.3.10
docker exec clab-http20-client curl -s -o /dev/null -w "%{http_code}\n" http://10.10.1.20:8888/index.html
```
Expected: traceroute shows 10.10.1.1, 10.10.2.2, 10.10.3.10; ping about 21 ms at the 20 ms setting; curl prints 200.
RTT check at the other settings: `./scripts/set_rtt.sh 100` (about 101 ms) and `./scripts/set_rtt.sh 200` (about 201 ms).
`./scripts/set_rtt.sh clear` removes the impairments.

## 4. Functional tests (live demo commands)
```
# 200, 301, 404, HEAD, POST (direct to origin)
docker exec clab-http20-client curl -si http://10.10.3.10:8080/index.html
docker exec clab-http20-client curl -si http://10.10.3.10:8080/old-page
docker exec clab-http20-client curl -si http://10.10.3.10:8080/missing
docker exec clab-http20-client curl -sI http://10.10.3.10:8080/index.html
docker exec clab-http20-client curl -si -d "name=cn-project-20-test" http://10.10.3.10:8080/echo

# Proxy: reset cache, MISS then HIT, then stats
docker exec clab-http20-client curl -s http://10.10.1.20:8888/__reset
docker exec clab-http20-client curl -si -o /dev/null -D - http://10.10.1.20:8888/style.css
docker exec clab-http20-client curl -si -o /dev/null -D - http://10.10.1.20:8888/style.css
docker exec clab-http20-client curl -s http://10.10.1.20:8888/__stats

# Date-based revalidation (origin sends no ETag on /noetag/): wait 12 s between the two requests (max-age is 10 s)
docker exec clab-http20-client curl -si -o /dev/null -D - http://10.10.1.20:8888/noetag/style.css
sleep 12
docker exec clab-http20-client curl -si -o /dev/null -D - http://10.10.1.20:8888/noetag/style.css
```
Look at the `X-Cache` header: MISS, HIT, REVALIDATED-304 or REVALIDATED-CHANGED.

## 5. Experiments
Main experiment (about 15 minutes, writes `results/raw.jsonl`):
```
./scripts/run_experiments.sh
python3 scripts/summarize.py
```
Each run times a page bundle (index.html plus 20 objects over 5 connections) and a 300-request load test at
concurrency 5. Mode C also runs cold, warm and stale page phases. Supplementary ApacheBench (writes `results/ab_raw.csv`):
```
./scripts/run_ab.sh
```
Note: ApacheBench speaks HTTP/1.0, so these results show the keep-alive effect but do not by themselves prove HTTP/1.1 persistence.

Draw the page-time and throughput chart used in the report (Figure 4) with `python3 scripts/make_results_chart.py` (writes `results/results_chart.png`; values are copied from `results/summary.csv`).

## 6. Packet captures
tshark cannot write to `/captures` directly, so capture to `/tmp` and copy out. Wait about 7 s after starting tshark
before sending traffic. Example (direct connection reuse, captured on R1 eth2):
```
docker exec -d clab-http20-r1 sh -c "timeout 25 tshark -i eth2 -f 'tcp port 8080' -w /tmp/NAME.pcapng"
sleep 7
# ... send traffic ...
docker exec clab-http20-r1 cp /tmp/NAME.pcapng /captures/
sudo chown $USER:$USER captures/*; chmod 644 captures/*
```
Capture points: direct client-origin traffic on R1 eth2 (tcp 8080); client-proxy leg on the proxy eth1 (tcp 8888);
proxy-origin leg on R2 eth2 (tcp 8080). Client and proxy share the bridge, so client-proxy traffic never reaches R1.
Read a capture: `docker exec clab-http20-r2 tshark -r /captures/FILE.pcapng -Y http`.

| File | Shows |
|---|---|
| 01_connection_reuse | 1 SYN, several requests on one connection |
| 02_connection_close | one connection per request, server FIN after each response |
| 03a/03b | proxy MISS then HIT; origin sees one request |
| 04a/04b | If-None-Match revalidation, 304 without body |
| 05a/05b | changed file: conditional GET returns 200 with a new ETag |
| 06_head, 07_post, 08_301, 09_404 | HEAD, POST /echo, 301 with Location, 404 |
| 10a/10b | If-Modified-Since revalidation (no ETag) |

## 7. Dashboard (outside the measured path)
```
docker run -d --name http20-dashboard -p 3000:3000 -v ~/http20:/proj -w /proj/dashboard node:20-alpine sh -c "npm install --no-audit --no-fund && node server.js"
```
Open http://localhost:3000. After a reboot use `docker start http20-dashboard`.

## 8. Architecture diagram
`python3 scripts/make_diagram.py` writes `diagram/architecture.png`.

## Known issues and notes
- **tbf burst:** a small tbf burst stalled transfers because veth TSO/GSO packets exceeded it. `set_rtt.sh` disables
  tso/gso/gro and uses `burst 100kb`, with netem `limit 10000`.
- The lab does not survive WSL restarts or sleep. Redeploy (section 1) and restart the services (section 2).
- `www/style.css` and `www/new-page.html` were edited during testing, so the file contents and ETags differ from a freshly generated site.
  This does not affect the results.
- Containers are Linux network namespaces, not VMs. Cache state is reset between experiments with `/__reset`.
