#!/usr/bin/env python3
"""Origin HTTP/1.1 server built on raw sockets (no http.server)."""
import argparse, hashlib, os, socket, sys, time
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate, parsedate_to_datetime
from urllib.parse import unquote, urlsplit

MIME = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".bin": "application/octet-stream", ".txt": "text/plain"}
REDIRECTS = {"/old-page": "/new-page.html"}
REASONS = {200: "OK", 301: "Moved Permanently", 304: "Not Modified",
           400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed"}

def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)

def make_etag(st):
    return '"' + hashlib.md5(f"{st.st_mtime_ns}-{st.st_size}".encode()).hexdigest()[:16] + '"'

def send(conn, status, headers, body=b"", head_only=False, keep_alive=True):
    headers = dict(headers)
    headers["Connection"] = "keep-alive" if keep_alive else "close"
    headers["Date"] = formatdate(usegmt=True)
    headers["Server"] = "CN-Project20/1.0"
    out = f"HTTP/1.1 {status} {REASONS[status]}\r\n"
    out += "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
    conn.sendall(out.encode() + (b"" if head_only or status == 304 else body))

def not_modified(req_headers, etag, mtime):
    """If-None-Match takes precedence over If-Modified-Since."""
    inm = req_headers.get("if-none-match")
    if inm is not None:
        if inm.strip() == "*":
            return True
        return etag in [t.strip().removeprefix("W/") for t in inm.split(",")]
    ims = req_headers.get("if-modified-since")
    if ims:
        try:
            return int(mtime) <= int(parsedate_to_datetime(ims).timestamp())
        except Exception:
            return False
    return False

def handle(conn, addr, root, max_age, idle):
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn.settimeout(idle)
    rfile = conn.makefile("rb")
    try:
        while True:  # requests on one connection are handled sequentially
            line = rfile.readline(65537)
            if not line:
                break
            parts = line.decode("latin-1").strip().split()
            if len(parts) != 3:
                send(conn, 400, {"Content-Length": "0"}, keep_alive=False)
                break
            method, target, version = parts
            hdrs = {}
            while True:
                h = rfile.readline(65537).decode("latin-1")
                if h in ("\r\n", "\n", ""):
                    break
                if ":" in h:
                    k, v = h.split(":", 1)
                    hdrs[k.strip().lower()] = v.strip()
            body = rfile.read(int(hdrs.get("content-length", 0) or 0))

            conn_hdr = hdrs.get("connection", "").lower()
            if version == "HTTP/1.0":
                keep = conn_hdr == "keep-alive"
            else:
                keep = conn_hdr != "close"

            path = unquote(urlsplit(target).path)
            head_only = method == "HEAD"
            status = 404

            if method == "POST" and path == "/echo":
                send(conn, 200, {"Content-Type": "text/plain",
                                 "Content-Length": str(len(body))}, body, keep_alive=keep)
                status = 200
            elif method not in ("GET", "HEAD", "POST"):
                send(conn, 405, {"Content-Length": "0", "Allow": "GET, HEAD, POST"}, keep_alive=keep)
                status = 405
            elif path in REDIRECTS:
                send(conn, 301, {"Location": REDIRECTS[path], "Content-Length": "0"},
                     keep_alive=keep)
                status = 301
            else:
                noetag = path.startswith("/noetag/"); rel = "index.html" if path == "/" else (path[8:] if noetag else path.lstrip("/"))
                fs = os.path.realpath(os.path.join(root, rel))
                if method != "POST" and fs.startswith(os.path.realpath(root) + os.sep) and os.path.isfile(fs):
                    st = os.stat(fs)
                    etag = None if noetag else make_etag(st)
                    lm = formatdate(st.st_mtime, usegmt=True)
                    base = {"Last-Modified": lm,
                            "Cache-Control": f"max-age={max_age}"}
                    if etag: base["ETag"] = etag
                    if not_modified(hdrs, etag, st.st_mtime):
                        send(conn, 304, base, keep_alive=keep)
                        status = 304
                    else:
                        with open(fs, "rb") as f:
                            data = f.read()
                        base["Content-Type"] = MIME.get(os.path.splitext(fs)[1], "application/octet-stream")
                        base["Content-Length"] = str(len(data))
                        send(conn, 200, base, data, head_only, keep)
                        status = 200
                else:
                    msg = b"<html><body><h1>404 Not Found</h1></body></html>\n"
                    send(conn, 404, {"Content-Type": "text/html",
                                     "Content-Length": str(len(msg))}, msg, head_only, keep)
            log(f"{addr[0]}:{addr[1]} {method} {path} {version} -> {status} "
                f"(INM={hdrs.get('if-none-match','-')} IMS={hdrs.get('if-modified-since','-')} keep={keep})")
            if not keep:
                break
    except (socket.timeout, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        rfile.close()
        conn.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--root", default="/www")
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--max-age", type=int, default=10, help="Cache-Control max-age (s)")
    ap.add_argument("--idle", type=float, default=15, help="keep-alive idle timeout (s)")
    a = ap.parse_args()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((a.host, a.port))
    srv.listen(256)
    log(f"origin listening on {a.host}:{a.port}, root={a.root}, workers={a.workers}")
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        while True:
            conn, addr = srv.accept()
            pool.submit(handle, conn, addr, a.root, a.max_age, a.idle)

if __name__ == "__main__":
    main()
