"""config/ 配下の設定ファイル読込。設定値はすべてここを経由して取得する。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
OVERRIDES_PATH = ROOT_DIR / "data" / "overrides.yaml"


def load_yaml(path: Path) -> Any:
    """YAMLを読み込む。ファイルが無い・空の場合は空dictを返す。"""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if data is not None else {}


@dataclass
class Config:
    """全設定ファイルの内容をまとめたもの。"""

    settings: dict[str, Any]
    sources: list[dict[str, Any]]
    keywords: dict[str, Any]
    categories: dict[str, Any]
    venues: dict[str, Any]
    known_urls: list[dict[str, Any]] = field(default_factory=list)
    root_dir: Path = ROOT_DIR

    def section(self, name: str) -> dict[str, Any]:
        return self.settings.get(name, {}) or {}

    @property
    def category_names(self) -> list[str]:
        return [c["name"] for c in self.categories.get("categories", [])]

    @property
    def category_fallback(self) -> str:
        return self.categories.get("fallback", "その他IT")

    def path(self, relative: str) -> Path:
        """settings.yaml に書かれたリポジトリ相対パスを絶対パスにする。"""
        return self.root_dir / relative

    @property
    def docs_data_dir(self) -> Path:
        return self.path(self.section("output").get("docs_data_dir", "docs/data"))

    @property
    def archive_dir(self) -> Path:
        return self.path(self.section("output").get("archive_dir", "data/archive"))


def load_config(config_dir: Path = CONFIG_DIR, root_dir: Path = ROOT_DIR) -> Config:
    return Config(
        settings=load_yaml(config_dir / "settings.yaml"),
        sources=load_yaml(config_dir / "sources.yaml").get("sources", []) or [],
        keywords=load_yaml(config_dir / "keywords.yaml"),
        categories=load_yaml(config_dir / "categories.yaml"),
        venues=load_yaml(config_dir / "venues.yaml"),
        known_urls=load_yaml(config_dir / "known_urls.yaml").get("urls", []) or [],
        root_dir=root_dir,
    )


def load_overrides(path: Path = OVERRIDES_PATH) -> dict[str, Any]:
    data = load_yaml(path)
    return {key: data.get(key) or [] for key in ("exclude", "fix", "merge", "confirm")}
