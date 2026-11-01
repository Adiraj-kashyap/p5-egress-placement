"""Per-edge byte accounting at the application layer for the M07 testbed (D-035).

Every outbound connection a service makes (web -> api over HTTP, api -> redis over RESP,
api -> postgres over the pg wire protocol) is wrapped in a CountingSocket, so the counters
hold the exact bytes the application wrote to and read from the TCP socket for that peer
(TCP payload; no IP/TCP/Ethernet headers). Inbound HTTP bytes are counted by an ASGI
middleware from the request/response lines, headers and bodies. Counters are exported as
JSON by each service's /metrics.json and zeroed by /reset.

Stdlib only, so the module is importable by the tests without the service dependencies.
"""
from __future__ import annotations

import http.client
import io
import socket
import threading
from typing import Any


class EdgeCounters:
    """Thread-safe byte counters keyed by peer name, plus a served-request counter."""

    def __init__(self, service: str) -> None:
        """Create empty counters for the named service (e.g. ``"web"``)."""
        self.service = service
        self._lock = threading.Lock()
        self._edges: dict[str, dict[str, int]] = {}
        self._requests = 0

    def add(self, peer: str, sent: int = 0, received: int = 0) -> None:
        """Add ``sent`` bytes (this service -> peer) and ``received`` bytes (peer -> this service)."""
        with self._lock:
            e = self._edges.setdefault(peer, {"bytes_sent": 0, "bytes_received": 0})
            e["bytes_sent"] += sent
            e["bytes_received"] += received

    def count_request(self) -> None:
        """Count one served business request (probes and metric scrapes are excluded)."""
        with self._lock:
            self._requests += 1

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable copy: service, requests and per-peer counters."""
        with self._lock:
            return {"service": self.service, "requests": self._requests,
                    "edges": {p: dict(v) for p, v in sorted(self._edges.items())}}

    def reset(self) -> None:
        """Zero every counter (keeps the peer keys so /metrics.json stays stable)."""
        with self._lock:
            for v in self._edges.values():
                v["bytes_sent"] = 0
                v["bytes_received"] = 0
            self._requests = 0


class CountingSocket:
    """Socket wrapper that credits every byte sent/received to one peer in EdgeCounters.

    Covers the calls used by http.client, redis-py (pure-Python parser) and pg8000:
    send, sendall, recv, recv_into and makefile (whose SocketIO routes back through this
    wrapper). Everything else is delegated to the real socket.
    """

    def __init__(self, sock: socket.socket, counters: EdgeCounters, peer: str) -> None:
        """Wrap ``sock``; bytes are credited to ``peer`` in ``counters``."""
        self._sock = sock
        self._counters = counters
        self._peer = peer

    def send(self, data: bytes, *args: Any) -> int:
        """Send like socket.send and count the bytes actually written."""
        n = self._sock.send(data, *args)
        self._counters.add(self._peer, sent=n)
        return n

    def sendall(self, data: bytes, *args: Any) -> None:
        """Send like socket.sendall and count the whole buffer."""
        self._sock.sendall(data, *args)
        self._counters.add(self._peer, sent=memoryview(data).nbytes)

    def recv(self, bufsize: int, *args: Any) -> bytes:
        """Receive like socket.recv and count the bytes returned."""
        b = self._sock.recv(bufsize, *args)
        self._counters.add(self._peer, received=len(b))
        return b

    def recv_into(self, buffer: Any, nbytes: int = 0, flags: int = 0) -> int:
        """Receive like socket.recv_into and count the bytes stored."""
        n = self._sock.recv_into(buffer, nbytes, flags)
        self._counters.add(self._peer, received=n)
        return n

    def makefile(self, mode: str = "r", buffering: int | None = None, *,
                 encoding: str | None = None, errors: str | None = None,
                 newline: str | None = None) -> Any:
        """Return a file object over this wrapper (mirrors socket.socket.makefile)."""
        reading, writing = "r" in mode, "w" in mode
        rawmode = ("r" if reading else "") + ("w" if writing else "")
        raw = socket.SocketIO(self, rawmode)  # type: ignore[arg-type]
        if buffering is None:
            buffering = -1
        if buffering < 0:
            buffering = io.DEFAULT_BUFFER_SIZE
        if buffering == 0:
            return raw
        if reading and writing:
            buffer: Any = io.BufferedRWPair(raw, raw, buffering)
        elif reading:
            buffer = io.BufferedReader(raw, buffering)
        else:
            buffer = io.BufferedWriter(raw, buffering)
        if "b" in mode:
            return buffer
        return io.TextIOWrapper(buffer, encoding, errors, newline)

    def _decref_socketios(self) -> None:
        """No-op hook that socket.SocketIO.close calls on its owner."""

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else (settimeout, setsockopt, close, fileno, ...)."""
        return getattr(self._sock, name)


class CountingHTTPConnection(http.client.HTTPConnection):
    """http.client connection whose socket is a CountingSocket for one peer."""

    def __init__(self, host: str, port: int, counters: EdgeCounters, peer: str,
                 timeout: float = 10.0) -> None:
        """Create a keep-alive HTTP connection to ``host:port`` counted as ``peer``."""
        super().__init__(host, port, timeout=timeout)
        self._counters = counters
        self._peer = peer

    def connect(self) -> None:
        """Open the TCP connection and wrap it for counting."""
        super().connect()
        self.sock = CountingSocket(self.sock, self._counters, self._peer)  # type: ignore[assignment]


def http_message_bytes(start_line: str, headers: list[tuple[bytes, bytes]], body_len: int) -> int:
    """Return the HTTP/1.1 wire size of a message: start line, headers, blank line, body."""
    size = len(start_line.encode("latin-1")) + 2
    for k, v in headers:
        size += len(k) + 2 + len(v) + 2
    return size + 2 + body_len


class InboundCountingMiddleware:
    """ASGI middleware that counts inbound HTTP bytes per client peer.

    Request size = request line + headers + body; response size = status line + headers +
    body, as they appear on the wire for HTTP/1.1 without chunking. Paths in ``skip`` (probes,
    /metrics.json, /reset) are neither counted as bytes nor as requests.
    """

    def __init__(self, app: Any, counters: EdgeCounters, peer: str,
                 skip: tuple[str, ...] = ("/metrics.json", "/reset", "/healthz")) -> None:
        """Wrap ``app``; inbound traffic is credited to ``peer`` (e.g. ``"client"``)."""
        self.app = app
        self.counters = counters
        self.peer = peer
        self.skip = skip

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        """Count one HTTP exchange, then delegate to the wrapped app."""
        if scope["type"] != "http" or scope["path"] in self.skip:
            await self.app(scope, receive, send)
            return
        target = scope.get("raw_path", scope["path"].encode()).decode("latin-1")
        if scope.get("query_string"):
            target += "?" + scope["query_string"].decode("latin-1")
        req_line = f"{scope['method']} {target} HTTP/{scope.get('http_version', '1.1')}"
        req_headers = list(scope.get("headers", []))
        state = {"req_body": 0, "resp": 0}

        async def counting_receive() -> dict:
            msg = await receive()
            if msg["type"] == "http.request":
                state["req_body"] += len(msg.get("body", b""))
            return msg

        async def counting_send(msg: dict) -> None:
            if msg["type"] == "http.response.start":
                status = msg["status"]
                state["resp"] += http_message_bytes(
                    f"HTTP/1.1 {status} {http.client.responses.get(status, '')}",
                    list(msg.get("headers", [])), 0)
            elif msg["type"] == "http.response.body":
                state["resp"] += len(msg.get("body", b""))
            await send(msg)

        await self.app(scope, counting_receive, counting_send)
        # uvicorn runs with --no-server-header --no-date-header, so the app's headers are all
        self.counters.add(self.peer,
                          sent=state["resp"],
                          received=http_message_bytes(req_line, req_headers, state["req_body"]))
        self.counters.count_request()
