"""汎用主催者ページ。本文をキーワード判定し、通過すれば Gemini で抽出する。"""

from __future__ import annotations

from collector.sources.venue_generic import Parser as VenueGenericParser


class Parser(VenueGenericParser):
    source_type = "organizer"
    label = "主催者HP"
    skip_keyword_filter = False
