"""収集元パーサーの登録。sources.yaml の type とモジュールを対応づける。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

PARSER_TYPES = {
    "jmesse": "collector.sources.jmesse",
    "venue_bigsight": "collector.sources.venue_bigsight",
    "venue_makuhari": "collector.sources.venue_makuhari",
    "venue_pacifico": "collector.sources.venue_pacifico",
    "venue_generic": "collector.sources.venue_generic",
    "organizer_generic": "collector.sources.organizer_generic",
    "known_urls": "collector.sources.known_urls",
}


def create_parser(source: dict[str, Any], fetcher: Any, context: dict[str, Any]) -> Any:
    module_name = PARSER_TYPES.get(source.get("type", ""))
    if module_name is None:
        raise ValueError(f"未知の収集元type: {source.get('type')}")
    return import_module(module_name).Parser(source, fetcher, context)
