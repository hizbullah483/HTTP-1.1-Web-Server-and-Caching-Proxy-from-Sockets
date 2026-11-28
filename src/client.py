#!/usr/bin/env python3
"""HTTP/1.1 measurement client (raw sockets). One run of one mode -> JSON on stdout."""
import argparse, json, re, socket, statistics, sys, threading, time

def read_response(rfile, method="GET"):
    line = rfile.readline(65537).decode("latin-1").strip()
    if not line:
        raise ConnectionError("closed")
    status = int(line.split()[1])
    hdrs = {}
    while True:
        h = rfile.readline(65537).decode("latin-1")
        if h in ("\r\n", "\n", ""):
            break
        k, v = h.split(":", 1)
        hdrs[k.strip().lower()] = v.strip()
    n = 0 if (method == "HEAD" or status in (204, 304)) else int(hdrs.get("content-length", 0) or 0)
    body = rfile.read(n) if n else b""
    return status, hdrs, body

class Conn:
    def __init__(self, host, port, persistent, counter):
        self.host, self.port, self.persistent, self.counter = host, port, persistent, counter
        self.sock = self.rfile = None

    def _open(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=30)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.rfile = self.sock.makefile("rb")
        self.counter[0] += 1  # one TCP connection (= one SYN) opened

    def close(self):
        for o in (self.rfile, self.sock):
            try: o and o.close()
            except Exception: pass
        self.sock = self.rfile = None

    def get(self, path, extra=""):
        if self.sock is None:
            self._open()
        conn_hdr = "keep-alive" if self.persistent else "close"
        req = (f"GET {path} HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n"
               f"Connection: {conn_hdr}\r\n{extra}\r\n")
        try:
            self.sock.sendall(req.encode())
            st, h, b = read_response(self.rfile)
        except (ConnectionError, OSError):
            self.close(); self._open()
            self.sock.sendall(req.encode())
            st, h, b = read_response(self.rfile)
        if not self.persistent or h.get("connection", "").lower() == "close":
            self.close()
        return st, h, b

def fetch_page(host, port, persistent, parallel, counter, fails):
    """Fetch index.html, parse the embedded objects, fetch them over `parallel` connections."""
    c = Conn(host, port, persistent, counter)
    st, h, body = c.get("/")
    nbytes = len(body)
    if st != 200:
        fails[0] += 1
    objs = re.findall(r'(?:src|href)="(/[^"]+)"', body.decode("latin-1"))
    lock = threading.Lock()
    queue = list(objs)
    total = [0]
    def worker(first_conn=None):
        cc = first_conn or Conn(host, port, persistent, counter)
        while True:
            with lock:
                if not queue: break
                p = queue.pop()
            try:
                s, hh, bb = cc.get(p)
                with lock:
                    total[0] += len(bb)
                    if s != 200: fails[0] += 1
            except Exception:
                with lock: fails[0] += 1
        cc.close()
    ths = [threading.Thread(target=worker, args=(c if i == 0 else None,)) for i in range(parallel)]
    # first worker reuses the connection that fetched index.html (persistent modes only)
    if not persistent:
        c.close(); ths = [threading.Thread(target=worker) for _ in range(parallel)]
    for t in ths: t.start()
    for t in ths: t.join()
    return len(objs), nbytes + total[0]

def timed_page(host, port, persistent, parallel):
    counter, fails = [0], [0]
    t0 = time.perf_counter()
    n, nb = fetch_page(host, port, persistent, parallel, counter, fails)
    return dict(time_s=round(time.perf_counter() - t0, 4), objects=n, bytes=nb,
                tcp_conns=counter[0], failures=fails[0])

def load_test(host, port, persistent, total, conc, paths):
    counter, fails, lat = [0], [0], []
    lock = threading.Lock()
    idx = [0]
    def worker():
        c = Conn(host, port, persistent, counter)
        while True:
            with lock:
                if idx[0] >= total: break
                i = idx[0]; idx[0] += 1
            t = time.perf_counter()
            try:
                s, h, b = c.get(paths[i % len(paths)])
                if s != 200: 
                    with lock: fails[0] += 1
            except Exception:
                with lock: fails[0] += 1
            with lock: lat.append(time.perf_counter() - t)
        c.close()
    t0 = time.perf_counter()
    ths = [threading.Thread(target=worker) for _ in range(conc)]
    for t in ths: t.start()
    for t in ths: t.join()
    el = time.perf_counter() - t0
    return dict(requests=total, concurrency=conc, time_s=round(el, 3), req_per_s=round(total / el, 2),
                tcp_conns=counter[0], failures=fails[0],
                mean_lat_ms=round(statistics.mean(lat) * 1000, 2))

def admin(host, port, path):
    counter = [0]
    c = Conn(host, port, False, counter)
    st, h, b = c.get(path)
    c.close()
    return json.loads(b) if path == "/__stats" else b.decode()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["A", "B", "C"])
    ap.add_argument("--origin", default="10.10.3.10:8080")
    ap.add_argument("--proxy", default="10.10.1.20:8888")
    ap.add_argument("--requests", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--stale-wait", type=float, default=11, help="seconds to wait so cache entries go stale")
    a = ap.parse_args()

    target = a.proxy if a.mode == "C" else a.origin
    host, port = target.split(":"); port = int(port)
    persistent = a.mode in ("B", "C")
    paths = ["/"] + [f"/img/pic{i:02d}.bin" for i in range(1, 19)] + ["/style.css", "/app.js"]
    res = dict(mode=a.mode, target=target)

    if a.mode == "C":
        ph, pp = a.proxy.split(":")
        admin(ph, int(pp), "/__reset")
        res["cold"] = timed_page(host, port, True, a.concurrency)
        res["warm"] = timed_page(host, port, True, a.concurrency)
        time.sleep(a.stale_wait)
        res["stale"] = timed_page(host, port, True, a.concurrency)
        admin(ph, int(pp), "/__reset")
        res["page"] = timed_page(host, port, True, a.concurrency)  # cold page = comparable to A/B
        admin(ph, int(pp), "/__reset")
    else:
        res["page"] = timed_page(host, port, persistent, a.concurrency)

    res["load"] = load_test(host, port, persistent, a.requests, a.concurrency, paths)
    if a.mode == "C":
        res["proxy_stats"] = admin(host, port, "/__stats")
    print(json.dumps(res))

if __name__ == "__main__":
    main()
