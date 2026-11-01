"""Locust workload for the M07 T1 testbed: weighted browse / detail / write mix.

Mix per task pick: browse a catalogue page 6, open a product page 3, place an order 1.
Popularity is skewed so the cache sees realistic hit ratios: 80% of browses hit pages 1-50
and 80% of detail views hit products 1-1000; the rest are uniform over the whole catalogue
(2,500 pages, 50,000 products). Each simulated user draws from its own random.Random seeded
from LOCUST_SEED (default 7) plus the user's index, so runs are repeatable in distribution.

Run (step 6 does this): locust -f testbed/load/locustfile.py --headless -u 20 -r 5 -t 10m
--host http://127.0.0.1:30080
"""
from __future__ import annotations

import itertools
import os
import random

from locust import HttpUser, between, task

SEED = int(os.environ.get("LOCUST_SEED", "7"))
N_PAGES, N_PRODUCTS = 2500, 50_000
HOT_PAGES, HOT_PRODUCTS, HOT_SHARE = 50, 1000, 0.8
_user_ids = itertools.count()


class Shopper(HttpUser):
    """One browsing user with a private seeded RNG."""

    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        """Give this user its own deterministic random stream."""
        self.rng = random.Random(SEED * 1_000_003 + next(_user_ids))

    def _pick(self, hot: int, total: int) -> int:
        """Return a 1-based id: from 1..hot with prob HOT_SHARE, else uniform over 1..total."""
        return self.rng.randint(1, hot) if self.rng.random() < HOT_SHARE else self.rng.randint(1, total)

    @task(6)
    def browse(self) -> None:
        """Open one catalogue page."""
        self.client.get(f"/?page_no={self._pick(HOT_PAGES, N_PAGES)}", name="/?page_no=[n]")

    @task(3)
    def detail(self) -> None:
        """Open one product page."""
        self.client.get(f"/product/{self._pick(HOT_PRODUCTS, N_PRODUCTS)}", name="/product/[id]")

    @task(1)
    def order(self) -> None:
        """Place one order for a product (the write path)."""
        self.client.post("/order", data={"product_id": self._pick(HOT_PRODUCTS, N_PRODUCTS),
                                         "qty": self.rng.randint(1, 3)}, name="/order")
