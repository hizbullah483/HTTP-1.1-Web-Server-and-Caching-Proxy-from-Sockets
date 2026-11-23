#!/usr/bin/env python3
"""Caching HTTP/1.1 proxy built on raw sockets."""
import argparse, json, re, socket, threading, time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

CACHE = {}
LOCK = threading.Lock()
STATS = dict(requests=0, fresh_hits=0, misses=0, revalidations=0,
             reval_304=0, reval_200=0, bypass=0, upstream_requests=0)
HOP = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "upgrade"}

def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)

def bump(k):
    with LOCK:
        STATS[k] += 1

def read_headers(rfile):
    hdrs = []
    while True:
        h = rfile.readline(65537).decode("latin-1")
        if h in ("\r\n", "\n", ""):
            break
        if ":" in h:
            k, v = h.split(":", 1)
            hdrs.append((k.strip(), v.strip()))
    return hdrs

def hget(hdrs, name, default=None):
    for k, v in hdrs:
        if k.lower() == name:
            return v
    return default

class Upstream:
    """One persistent connection to the origin, owned by one client connection."""
    def __init__(self, host, port):
        self.host, self.port, self.sock, self.rfile = host, port, None, None

    def _connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=30)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.rfile = self.sock.makefile("rb")

    def close(self):
        for o in (self.rfile, self.sock):
            try:
                o and o.close()
            except Exception:
                pass
        self.sock = self.rfile = None

    def _once(self, method, path, hdrs, body):
        req = f"{method} {path} HTTP/1.1\r\nHost: {self.host}:{self.port}\r\nConnection: keep-alive\r\n"
        for k, v in hdrs:
            req += f"{k}: {v}\r\n"
        if body:
            req += f"Content-Length: {len(body)}\r\n"
        self.sock.sendall(req.encode() + b"\r\n" + body)
        line = self.rfile.readline(65537).decode("latin-1").strip()
        if not line:
            raise ConnectionError("upstream closed")
        status = int(line.split()[1])
        rh = read_headers(self.rfile)
        n = 0 if (method == "HEAD" or status in (204, 304)) else int(hget(rh, "content-length", 0) or 0)
        data = self.rfile.read(n) if n else b""
        if hget(rh, "connection", "").lower() == "close":
            self.close()
        return status, rh, data

    def request(self, method, path, hdrs=(), body=b""):
        bump("upstream_requests")
        if self.sock is None:
            self._connect()
        try:
            return self._once(method, path, hdrs, body)
        except (ConnectionError, OSError):
            self._connect()  # origin closed the idle connection: retry once
            return self._once(method, path, hdrs, body)

def max_age_of(rh):
    m = re.search(r"max-age=(\d+)", hget(rh, "cache-control", "") or "")
    return int(m.group(1)) if m else 0

def respond(conn, status, reason, hdrs, body, xcache, keep, head_only=False):
    out = f"HTTP/1.1 {status} {reason}\r\n"
    for k, v in hdrs:
        if k.lower() not in HOP:
            out += f"{k}: {v}\r\n"
    out += f"X-Cache: {xcache}\r\nVia: 1.1 cn-proxy\r\nConnection: {'keep-alive' if keep else 'close'}\r\n\r\n"
    conn.sendall(out.encode() + (b"" if head_only else body))

REASON = {200: "OK", 301: "Moved Permanently", 304: "Not Modified", 400: "Bad Request",
          404: "Not Found", 405: "Method Not Allowed", 502: "Bad Gateway"}

def serve_get(conn, up, path, cond, keep):
    now = time.time()
    with LOCK:
        e = CACHE.get(path)
    if cond:  # client sent its own validators: pass straight through
        bump("bypass")
        st, rh, data = up.request("GET", path, cond)
        respond(conn, st, REASON.get(st, ""), rh, data, "BYPASS", keep, head_only=(st == 304))
        return st, "BYPASS"
    if e and now - e["stored"] < e["max_age"]:
        bump("fresh_hits")
        hdrs = [(k, v) for k, v in e["headers"]] + [("Age", str(int(now - e["stored"])))]
        respond(conn, 200, "OK", hdrs, e["body"], "HIT", keep)
        return 200, "HIT (no upstream)"
    if e:
        bump("revalidations")
        v = [("If-None-Match", e["etag"])] if e["etag"] else \
            [("If-Modified-Since", e["lm"])] if e["lm"] else []
        st, rh, data = up.request("GET", path, v)
        if st == 304:
            bump("reval_304")
            with LOCK:
                e["stored"] = time.time()
                e["max_age"] = max_age_of(rh) or e["max_age"]
            respond(conn, 200, "OK", e["headers"], e["body"], "REVALIDATED-304", keep)
            return 200, "REVALIDATE -> 304, served from cache"
        bump("reval_200")
        label = "REVALIDATED-CHANGED"
    else:
        bump("misses")
        st, rh, data = up.request("GET", path)
        label = "MISS"
    if st == 200 and max_age_of(rh) > 0:
        with LOCK:
            CACHE[path] = dict(headers=rh, body=data, etag=hget(rh, "etag"), lm=hget(rh, "last-modified"),
                               stored=time.time(), max_age=max_age_of(rh))
    elif st != 200:
        with LOCK:
            CACHE.pop(path, None)
    respond(conn, st, REASON.get(st, ""), rh, data, label, keep)
    return st, label

def handle(conn, addr, oh, op, idle):
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn.settimeout(idle)
    rfile = conn.makefile("rb")
    up = Upstream(oh, op)
    try:
        while True:
            line = rfile.readline(65537)
            if not line:
                break
            parts = line.decode("latin-1").strip().split()
            if len(parts) != 3:
                break
            method, target, version = parts
            hdrs = read_headers(rfile)
            body = rfile.read(int(hget(hdrs, "content-length", 0) or 0))
            ch = (hget(hdrs, "connection", "") or "").lower()
            keep = (ch == "keep-alive") if version == "HTTP/1.0" else (ch != "close")
            path = urlsplit(target).path or "/"
            if urlsplit(target).query:
                path += "?" + urlsplit(target).query
            if path == "/__stats":
                with LOCK:
                    s = dict(STATS, cache_entries=len(CACHE))
                    s["hit_ratio"] = round(s["fresh_hits"] / s["requests"], 4) if s["requests"] else 0
                b = json.dumps(s).encode()
                respond(conn, 200, "OK", [("Content-Type", "application/json"), ("Content-Length", str(len(b)))], b, "-", keep)
                if not keep: break
                continue
            if path == "/__reset":
                with LOCK:
                    CACHE.clear()
                    for k in STATS: STATS[k] = 0
                respond(conn, 200, "OK", [("Content-Length", "6")], b"reset\n", "-", keep)
                if not keep: break
                continue
            bump("requests")
            fwd = [(k, v) for k, v in hdrs if k.lower() not in HOP and
                   k.lower() not in ("host", "content-length", "if-none-match", "if-modified-since")]
            cond = [(k, v) for k, v in hdrs if k.lower() in ("if-none-match", "if-modified-since")]
            try:
                if method == "GET":
                    st, note = serve_get(conn, up, path, cond, keep)
                else:  # HEAD, POST and anything else: forward, never cache
                    bump("bypass")
                    st, rh, data = up.request(method, path, fwd + cond, body)
                    respond(conn, st, REASON.get(st, ""), rh, data, "BYPASS", keep, head_only=(method == "HEAD"))
                    note = "BYPASS (not cacheable)"
            except Exception as ex:
                msg = b"Bad Gateway\n"
                respond(conn, 502, "Bad Gateway", [("Content-Length", str(len(msg)))], msg, "ERROR", False)
                log(f"{addr[0]} {method} {path} -> 502 ({ex})")
                break
            log(f"{addr[0]}:{addr[1]} {method} {path} -> {st} [{note}]")
            if not keep:
                break
    except (socket.timeout, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        up.close(); rfile.close(); conn.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8888)
    ap.add_argument("--origin-host", default="10.10.3.10")
    ap.add_argument("--origin-port", type=int, default=8080)
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--idle", type=float, default=15)
    a = ap.parse_args()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", a.port)); srv.listen(256)
    log(f"proxy listening on :{a.port} -> origin {a.origin_host}:{a.origin_port}")
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        while True:
            c, ad = srv.accept()
            pool.submit(handle, c, ad, a.origin_host, a.origin_port, a.idle)

if __name__ == "__main__":
    main()
