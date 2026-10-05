"""J-messe（ジェトロ 世界の見本市・展示会情報）。

2026-10-05 時点で、トップページの検索フォームの送信先（/j-messe/tradefair/search.html）が 404 を返し、
検索結果ページを取得できない。推測で実装せず無効化している（README「収集元の状況」参照）。
"""

from __future__ import annotations

from collector.sources.base import DisabledSource


class Parser(DisabledSource):
    reason = "検索ページが404のため未対応（README参照）"
