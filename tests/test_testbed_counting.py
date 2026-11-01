"""Tests for the M07 testbed byte counters (testbed/app/common/counting.py)."""
from __future__ import annotations

import asyncio
import http.server
import importlib.util
import socket
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("counting", ROOT / "testbed/app/common/counting.py")
counting = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(counting)


def test_counting_socket_counts_both_directions() -> None:
    a, b = socket.socketpair()
    c = counting.EdgeCounters("t")
    wa = counting.CountingSocket(a, c, "peer")
    wa.sendall(b"x" * 1000)
    assert b.recv(2000) == b"x" * 1000
    b.sendall(b"y" * 300)
    buf = bytearray(500)
    n = wa.recv_into(buf)
    assert n == 300
    snap = c.snapshot()
    assert snap["edges"]["peer"] == {"bytes_sent": 1000, "bytes_received": 300}
    a.close(); b.close()


def test_makefile_routes_through_counter() -> None:
    a, b = socket.socketpair()
    c = counting.EdgeCounters("t")
    f = counting.CountingSocket(a, c, "p").makefile("rwb")
    f.write(b"hello\n"); f.flush()
    assert b.recv(10) == b"hello\n"
    b.sendall(b"world\n")
    assert f.readline() == b"world\n"
    assert c.snapshot()["edges"]["p"] == {"bytes_sent": 6, "bytes_received": 6}
    a.close(); b.close()


def test_reset_zeroes_counters_and_requests() -> None:
    c = counting.EdgeCounters("t")
    c.add("p", sent=5, received=7)
    c.count_request()
    c.reset()
    assert c.snapshot() == {"service": "t", "requests": 0,
                            "edges": {"p": {"bytes_sent": 0, "bytes_received": 0}}}


def test_http_connection_counts_exact_wire_bytes() -> None:
    body = b"z" * 4321

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a) -> None:
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    c = counting.EdgeCounters("web")
    conn = counting.CountingHTTPConnection("127.0.0.1", srv.server_port, c, "api")
    for _ in range(3):  # keep-alive reuse
        conn.request("GET", "/x")
        r = conn.getresponse()
        assert r.read() == body
    e = c.snapshot()["edges"]["api"]
    assert e["bytes_received"] > 3 * len(body)
    assert e["bytes_received"] < 3 * (len(body) + 300)
    assert 3 * 40 < e["bytes_sent"] < 3 * 200
    conn.close(); srv.shutdown()


def test_http_message_bytes() -> None:
    # "GET / HTTP/1.1\r\n" + "host: a\r\n" + "\r\n" + 3-byte body
    assert counting.http_message_bytes("GET / HTTP/1.1", [(b"host", b"a")], 3) == 16 + 9 + 2 + 3


def test_inbound_middleware_counts_and_skips_probes() -> None:
    c = counting.EdgeCounters("web")

    async def app(scope, receive, send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"5")]})
        await send({"type": "http.response.body", "body": b"hello"})

    mw = counting.InboundCountingMiddleware(app, c, "client")

    async def receive() -> dict:
        return {"type": "http.request", "body": b"ab", "more_body": False}

    async def send(msg) -> None:
        pass

    def scope(path: str) -> dict:
        return {"type": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
                "method": "POST", "http_version": "1.1", "headers": [(b"host", b"w")]}

    asyncio.run(mw(scope("/order"), receive, send))
    asyncio.run(mw(scope("/healthz"), receive, send))
    snap = c.snapshot()
    assert snap["requests"] == 1
    # "POST /order HTTP/1.1\r\n"(22) + "host: w\r\n"(9) + "\r\n"(2) + body 2
    assert snap["edges"]["client"]["bytes_received"] == 35
    # "HTTP/1.1 200 OK\r\n"(17) + "content-length: 5\r\n"(19) + "\r\n"(2) + body 5
    assert snap["edges"]["client"]["bytes_sent"] == 43
