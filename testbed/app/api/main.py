"""T1 testbed `api` service: product catalogue over postgres (`db`), cached in redis (`cache`).

Endpoints: GET /products?page=N (20 products per page), GET /products/{id} (product and four
related products), POST /orders (the one write path), plus /healthz, /metrics.json and /reset.
Every byte api exchanges with web, cache and db is counted per peer (testbed/app/common/counting.py).
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
from typing import Any

import pg8000.native
import redis
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from counting import CountingSocket, EdgeCounters, InboundCountingMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("api")

PAGE_SIZE = 20
CACHE_TTL_S = int(os.environ.get("CACHE_TTL_S", "60"))
DB = dict(host=os.environ.get("DB_HOST", "db"), port=int(os.environ.get("DB_PORT", "5432")),
          user=os.environ.get("DB_USER", "p5"), password=os.environ.get("DB_PASSWORD", "p5"),
          database=os.environ.get("DB_NAME", "p5"))

counters = EdgeCounters("api")


class CountingRedisConnection(redis.Connection):
    """redis-py connection whose socket credits bytes to the `cache` edge."""

    def _connect(self) -> Any:
        """Open the socket as redis-py does, then wrap it for counting."""
        return CountingSocket(super()._connect(), counters, "cache")


cache = redis.Redis(connection_pool=redis.ConnectionPool(
    connection_class=CountingRedisConnection, host=os.environ.get("CACHE_HOST", "cache"),
    port=int(os.environ.get("CACHE_PORT", "6379"))))

_local = threading.local()


def db_conn() -> pg8000.native.Connection:
    """Return this worker thread's postgres connection, opening a counted one if needed."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        raw = socket.create_connection((DB["host"], DB["port"]), timeout=10)
        conn = pg8000.native.Connection(DB["user"], password=DB["password"], database=DB["database"],
                                        sock=CountingSocket(raw, counters, "db"))
        _local.conn = conn
    return conn


def db_run(sql: str, **params: Any) -> list[dict[str, Any]]:
    """Run one statement on the thread's connection and return rows as dicts."""
    conn = db_conn()
    try:
        rows = conn.run(sql, **params)
    except Exception:
        _local.conn = None
        raise
    cols = [c["name"] for c in (conn.columns or [])]
    return [dict(zip(cols, r)) for r in rows]


def _jsonable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Decimal/datetime values so rows serialise to JSON."""
    return [{k: (str(v) if not isinstance(v, (int, str, type(None))) else v) for k, v in r.items()}
            for r in rows]


def cached(key: str, loader: Any) -> bytes:
    """Return the JSON bytes for ``key`` from redis, or load, store with TTL and return them."""
    hit = cache.get(key)
    if hit is not None:
        return hit
    body = json.dumps(loader()).encode()
    cache.setex(key, CACHE_TTL_S, body)
    return body


class Order(BaseModel):
    """Order request body."""
    product_id: int
    qty: int = 1


app = FastAPI(title="p5-api")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness/readiness probe."""
    return {"status": "ok"}


@app.get("/products")
def products(page: int = 1) -> Response:
    """Return one page of 20 products (cache-aside, TTL CACHE_TTL_S)."""
    lo = (max(page, 1) - 1) * PAGE_SIZE
    body = cached(f"list:{page}", lambda: _jsonable(db_run(
        "SELECT id, name, category, price, description FROM products "
        "WHERE id > :lo AND id <= :hi ORDER BY id", lo=lo, hi=lo + PAGE_SIZE)))
    return Response(body, media_type="application/json")


@app.get("/products/{pid}")
def product(pid: int) -> Response:
    """Return one product and four related products in its category (cache-aside)."""
    def load() -> dict[str, Any]:
        rows = db_run("SELECT id, name, category, price, description, stock FROM products "
                      "WHERE id = :pid", pid=pid)
        if not rows:
            raise HTTPException(404, "no such product")
        related = db_run("SELECT id, name, price FROM products WHERE category = :c AND id <> :pid "
                         "ORDER BY id LIMIT 4", c=rows[0]["category"], pid=pid)
        return {"product": _jsonable(rows)[0], "related": _jsonable(related)}
    return Response(cached(f"p:{pid}", load), media_type="application/json")


@app.post("/orders")
def create_order(order: Order) -> dict[str, Any]:
    """Insert one order row and return its id and timestamp (the write path, never cached)."""
    rows = db_run("INSERT INTO orders (product_id, qty) VALUES (:p, :q) RETURNING id, created_at",
                  p=order.product_id, q=order.qty)
    return _jsonable(rows)[0]


@app.get("/metrics.json")
def metrics() -> dict[str, Any]:
    """Per-edge byte counters and served-request count since the last /reset."""
    return counters.snapshot()


@app.post("/reset")
def reset(flush_cache: bool = False) -> dict[str, Any]:
    """Optionally FLUSHALL the cache (cold start for a run), then zero the counters."""
    if flush_cache:
        cache.flushall()
    counters.reset()
    log.info("counters reset flush_cache=%s", flush_cache)
    return counters.snapshot()


app.add_middleware(InboundCountingMiddleware, counters=counters, peer="web")
