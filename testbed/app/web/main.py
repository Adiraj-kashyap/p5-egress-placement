"""T1 testbed `web` service: renders HTML pages for end users from the `api` service.

Pages: GET / ?page=N (catalogue page), GET /product/{id} (detail page), POST /order (form
post, the write path), plus /healthz, /metrics.json and /reset. Bytes to/from api are counted
on the socket; bytes to/from end users are counted as the `client` edge (internet egress).
"""
from __future__ import annotations

import html
import http.client
import json
import logging
import os
import threading
from typing import Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse

from counting import CountingHTTPConnection, EdgeCounters, InboundCountingMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("web")

API_HOST = os.environ.get("API_HOST", "api")
API_PORT = int(os.environ.get("API_PORT", "8000"))

counters = EdgeCounters("web")
_local = threading.local()

# Fixed page chrome (inline CSS + nav + footer) so pages have a realistic, constant overhead.
STYLE = ("body{font-family:system-ui,sans-serif;margin:0;color:#222}header,footer{background:#123;"
         "color:#fff;padding:12px 24px}main{padding:16px 24px}table{border-collapse:collapse;width:100%}"
         "td,th{border-bottom:1px solid #ddd;padding:6px;text-align:left}.price{font-weight:600}"
         "p.desc{color:#555;max-width:60em}.related li{margin:4px 0}") * 4
HEAD = (f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{{title}}</title>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'><style>{STYLE}</style>"
        "</head><body><header><strong>P5 Shop</strong> <nav><a href='/'>Catalogue</a></nav></header><main>")
FOOT = "</main><footer>P5 testbed shop - synthetic catalogue for traffic measurement.</footer></body></html>"


def api_call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Call api over this thread's keep-alive connection and return the decoded JSON body."""
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    for attempt in (1, 2):
        conn = getattr(_local, "conn", None)
        if conn is None:
            conn = _local.conn = CountingHTTPConnection(API_HOST, API_PORT, counters, "api")
        try:
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except (http.client.HTTPException, OSError):
            conn.close()
            _local.conn = None
            if attempt == 2:
                raise
            continue
        if resp.status == 404:
            raise HTTPException(404, "not found")
        if resp.status >= 400:
            raise HTTPException(502, f"api returned {resp.status}")
        return json.loads(data)
    raise RuntimeError("unreachable")


def page(title: str, content: str) -> HTMLResponse:
    """Wrap ``content`` in the fixed page chrome."""
    return HTMLResponse(HEAD.replace("{title}", html.escape(title)) + content + FOOT)


app = FastAPI(title="p5-web")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness/readiness probe."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def catalogue(page_no: int = 1) -> HTMLResponse:
    """Render one catalogue page (20 products) from api /products."""
    rows = api_call("GET", f"/products?page={page_no}")
    trs = "".join(
        f"<tr><td><a href='/product/{r['id']}'>{html.escape(r['name'])}</a></td>"
        f"<td>{html.escape(r['category'])}</td><td class=price>${r['price']}</td>"
        f"<td>{html.escape(r['description'][:120])}</td></tr>" for r in rows)
    nav = f"<p><a href='/?page_no={max(page_no - 1, 1)}'>prev</a> | <a href='/?page_no={page_no + 1}'>next</a></p>"
    return page(f"Catalogue page {page_no}",
                f"<h1>Catalogue page {page_no}</h1><table><tr><th>Product</th><th>Category</th>"
                f"<th>Price</th><th>Summary</th></tr>{trs}</table>{nav}")


@app.get("/product/{pid}", response_class=HTMLResponse)
def product(pid: int) -> HTMLResponse:
    """Render one product page with related products from api /products/{id}."""
    d = api_call("GET", f"/products/{pid}")
    p = d["product"]
    rel = "".join(f"<li><a href='/product/{r['id']}'>{html.escape(r['name'])}</a> ${r['price']}</li>"
                  for r in d["related"])
    return page(p["name"],
                f"<h1>{html.escape(p['name'])}</h1><p class=price>${p['price']} - {p['stock']} in stock</p>"
                f"<p>Category: {html.escape(p['category'])}</p><p class=desc>{html.escape(p['description'])}</p>"
                f"<form method=post action='/order'><input type=hidden name=product_id value={p['id']}>"
                f"<input name=qty value=1><button>Order</button></form>"
                f"<h2>Related</h2><ul class=related>{rel}</ul>")


@app.post("/order", response_class=HTMLResponse)
def order(product_id: int = Form(...), qty: int = Form(1)) -> HTMLResponse:
    """Place an order through api POST /orders and render the confirmation."""
    o = api_call("POST", "/orders", {"product_id": product_id, "qty": qty})
    return page("Order placed", f"<h1>Order {o['id']} placed</h1><p>{qty} x product {product_id} "
                                f"at {html.escape(o['created_at'])}.</p><p><a href='/'>Back</a></p>")


@app.get("/metrics.json")
def metrics() -> dict[str, Any]:
    """Per-edge byte counters and served-request count since the last /reset."""
    return counters.snapshot()


@app.post("/reset")
def reset() -> dict[str, Any]:
    """Zero the counters."""
    counters.reset()
    log.info("counters reset")
    return counters.snapshot()


app.add_middleware(InboundCountingMiddleware, counters=counters, peer="client")
