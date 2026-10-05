"""HTTP取得・キャッシュ・robots.txt。ネットワークアクセスはすべてこのモジュールを経由する。

- 同一ドメインへのリクエスト間隔を interval_sec 以上空ける
- robots.txt を尊重する（取得できない場合は許可とみなす）
- 失敗時は retries 回まで指数バックオフで再試行（4xx は再試行しない）
- data/cache にレスポンス本文をキャッシュ（cache_ttl_hours 以内は再取得しない）
- PDF は pypdf でテキスト化する
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status: int = 0
    text: str = ""
    content_type: str = ""
    error: str = ""
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 300


class Fetcher:
    def __init__(self, fetch_cfg: dict[str, Any], cache_dir: Path | None = None, session: requests.Session | None = None) -> None:
        self.user_agent: str = fetch_cfg.get("user_agent", "exhibition-radar/1.0")
        self.interval: float = float(fetch_cfg.get("interval_sec", 2))
        self.timeout: float = float(fetch_cfg.get("timeout_sec", 20))
        self.retries: int = int(fetch_cfg.get("retries", 3))
        self.respect_robots: bool = bool(fetch_cfg.get("respect_robots_txt", True))
        self.cache_ttl: float = float(fetch_cfg.get("cache_ttl_hours", 0)) * 3600
        self.cache_dir = cache_dir
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent, "Accept-Language": "ja,en;q=0.8"})
        self._last_access: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.pages_fetched = 0

    # ------------------------------------------------------------ 内部
    def _wait(self, host: str) -> None:
        last = self._last_access.get(host)
        if last is not None:
            delay = self.interval - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
        self._last_access[host] = time.monotonic()

    def _robots_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            try:
                self._wait(parts.netloc)
                res = self.session.get(f"{base}/robots.txt", timeout=self.timeout)
                if res.status_code >= 400:
                    parser = None  # robots.txt が無い＝制限なし
                else:
                    parser.parse(res.text.splitlines())
            except requests.RequestException:
                parser = None
            self._robots[base] = parser
        parser = self._robots[base]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def _cache_path(self, url: str, params: dict[str, Any] | None) -> Path | None:
        if not self.cache_dir or self.cache_ttl <= 0:
            return None
        key = url + ("?" + json.dumps(params, sort_keys=True, ensure_ascii=False) if params else "")
        return self.cache_dir / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")

    def _read_cache(self, path: Path | None) -> FetchResult | None:
        if path is None or not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.cache_ttl:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return FetchResult(**data, from_cache=True)
        except (ValueError, TypeError):
            return None

    def _write_cache(self, path: Path | None, result: FetchResult) -> None:
        if path is None or not result.ok:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in result.__dict__.items() if k != "from_cache"}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _decode(res: requests.Response) -> str:
        ctype = res.headers.get("content-type", "").lower()
        if "pdf" in ctype or res.url.lower().endswith(".pdf"):
            return pdf_to_text(res.content)
        declared = re.search(r"charset=([\w-]+)", ctype)
        if declared:
            res.encoding = declared.group(1)
        else:
            meta = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", res.content[:4096], re.IGNORECASE)
            res.encoding = meta.group(1).decode("ascii") if meta else (res.apparent_encoding or "utf-8")
        return res.text

    # ------------------------------------------------------------ 公開API
    def get(self, url: str, params: dict[str, Any] | None = None, use_cache: bool = True) -> FetchResult:
        cache_path = self._cache_path(url, params) if use_cache else None
        cached = self._read_cache(cache_path)
        if cached:
            return cached
        if not self._robots_allowed(url):
            return FetchResult(url=url, error="robots.txt により取得禁止")

        host = urlsplit(url).netloc
        error = ""
        for attempt in range(self.retries + 1):
            self._wait(host)
            try:
                res = self.session.get(url, params=params, timeout=self.timeout, allow_redirects=True)
                self.pages_fetched += 1
            except requests.RequestException as exc:
                error = f"{type(exc).__name__}"
            else:
                if res.status_code < 400:
                    result = FetchResult(
                        url=url,
                        final_url=res.url,
                        status=res.status_code,
                        text=self._decode(res),
                        content_type=res.headers.get("content-type", ""),
                    )
                    self._write_cache(cache_path, result)
                    return result
                error = f"HTTP {res.status_code}"
                if res.status_code < 500 and res.status_code != 429:
                    return FetchResult(url=url, final_url=res.url, status=res.status_code, error=error)
            if attempt < self.retries:
                time.sleep(min(2**attempt * self.interval, 30))
        return FetchResult(url=url, error=error)


def pdf_to_text(content: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:20])
    except Exception as exc:  # pypdf は壊れたPDFで様々な例外を投げる
        log.warning("PDF解析失敗: %s", exc)
        return ""


def html_to_text(html: str, max_chars: int | None = None) -> tuple[str, str]:
    """(タイトル, 本文テキスト) を返す。script/style/nav/footer 等は除去する。"""
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer", "form"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)
    if max_chars:
        text = text[:max_chars]
    return title, text
