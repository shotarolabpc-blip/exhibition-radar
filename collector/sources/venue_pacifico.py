"""パシフィコ横浜。

2026-10-05 時点で、設計書のカレンダーURL（/visitor/calendar）は 404。
サイトは STUDIO（ノーコードCMS）製で、イベント一覧は JavaScript で描画されるため、HTMLからは取得できない。
推測で実装せず無効化している（README「収集元の状況」参照）。パシフィコ開催分は既知URL巡回で補完する。
"""

from __future__ import annotations

from collector.sources.base import DisabledSource


class Parser(DisabledSource):
    reason = "イベント一覧がJavaScript描画のため未対応（README参照）"
