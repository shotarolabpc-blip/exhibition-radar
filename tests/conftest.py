from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from collector.fetcher import FetchResult
from collector.settings import Config, load_config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def cfg() -> Config:
    return load_config()


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """外部通信をしない Fetcher の代わり。routes に (url, params) → 本文 or ステータスを登録する。"""

    def __init__(self, routes: dict[Any, Any] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.pages_fetched = 0

    def get(self, url: str, params: dict[str, Any] | None = None, use_cache: bool = True) -> FetchResult:
        self.calls.append((url, params))
        key = (url, tuple(sorted((params or {}).items())))
        body = self.routes.get(key, self.routes.get(url))
        if body is None:
            return FetchResult(url=url, status=404, error="HTTP 404")
        if isinstance(body, int):
            return FetchResult(url=url, status=body, error=f"HTTP {body}")
        self.pages_fetched += 1
        return FetchResult(url=url, final_url=url, status=200, text=body, content_type="text/html")


@pytest.fixture
def fake_fetcher() -> type[FakeFetcher]:
    return FakeFetcher
