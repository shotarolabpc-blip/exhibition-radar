"""会場 → 都道府県 → 地方区分。"""

from __future__ import annotations

from typing import Any

from collector.normalizer import clean_text, match_key

REGIONS = ("北海道・東北", "関東", "中部", "近畿", "中国・四国", "九州・沖縄", "オンライン")


def prefecture_to_region(prefecture: str, venues_cfg: dict[str, Any]) -> str:
    for region, prefs in (venues_cfg.get("regions") or {}).items():
        if prefecture in prefs:
            return region
    return ""


def resolve_region(venue: str, raw_venue: str, venues_cfg: dict[str, Any]) -> tuple[str, str]:
    """(都道府県, 地方区分) を返す。判定できなければ ("", "")。

    1. 正規化済み会場名が会場辞書にあればその値
    2. 会場文字列に都道府県名が含まれていればその県
    3. 会場文字列に cities の市名などが含まれていればその県
    """
    for v in venues_cfg.get("venues", []) or []:
        if v["name"] == venue:
            return v.get("prefecture", ""), v.get("region", "")

    text = clean_text(raw_venue or venue)
    all_prefs = [p for prefs in (venues_cfg.get("regions") or {}).values() for p in prefs]
    for pref in sorted(all_prefs, key=len, reverse=True):
        if pref in text:
            return pref, prefecture_to_region(pref, venues_cfg)

    key = match_key(text)
    cities = venues_cfg.get("cities") or {}
    for city in sorted(cities, key=len, reverse=True):
        if match_key(city) in key:
            pref = cities[city]
            return pref, prefecture_to_region(pref, venues_cfg)
    return "", ""
