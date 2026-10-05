"""data/overrides.yaml（人手補正）の適用（C-08）。"""

from __future__ import annotations

from typing import Any

from collector.models import Event, compose_event_name
from collector.normalizer import normalize_categories, normalize_url, normalize_venue
from collector.region import resolve_region

FIXABLE_FIELDS = (
    "event_name",
    "parent_event_name",
    "sub_event_name",
    "start_date",
    "end_date",
    "date_status",
    "venue",
    "prefecture",
    "region",
    "categories",
    "summary",
    "url",
)


def is_excluded(event: Event, overrides: dict[str, Any]) -> str | None:
    """除外対象なら理由を返す。"""
    for rule in overrides.get("exclude") or []:
        if rule.get("id") and rule["id"] == event.id:
            return rule.get("reason") or "人手で除外"
        needle = rule.get("url_contains")
        if needle and event.url and needle in event.url:
            return rule.get("reason") or "人手で除外"
    return None


def apply_fix(event: Event, fix: dict[str, Any], cfg_venues: dict[str, Any], cfg_categories: dict[str, Any]) -> list[str]:
    """fix 1件を適用し、実際に変わった項目名を返す。IDは変えない。"""
    changed: list[str] = []
    for name in FIXABLE_FIELDS:
        if name not in fix:
            continue
        value = fix[name]
        if name == "categories":
            value = normalize_categories(value, cfg_categories)
        elif name == "venue":
            value = normalize_venue(value, cfg_venues)
        elif name == "url":
            value = normalize_url(value)
        elif value is None:
            value = ""
        else:
            value = str(value)
        if getattr(event, name) != value:
            setattr(event, name, value)
            changed.append(name)

    if ("parent_event_name" in changed or "sub_event_name" in changed) and "event_name" not in fix:
        event.event_name = compose_event_name(event.parent_event_name, event.sub_event_name)
    if "venue" in changed and "prefecture" not in fix and "region" not in fix:
        event.prefecture, event.region = resolve_region(event.venue, event.venue, cfg_venues)
    if ("start_date" in changed or "end_date" in changed) and "date_status" not in fix:
        event.date_status = "fixed" if event.start_date else "unknown"
    return changed


def fixes_by_id(overrides: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["id"]: f for f in overrides.get("fix") or [] if f.get("id")}


def apply_overrides(
    events: list[Event],
    overrides: dict[str, Any],
    cfg_venues: dict[str, Any],
    cfg_categories: dict[str, Any],
    today: str,
) -> list[Event]:
    """統合 → 修正 → 除外 → 確認済み の順に適用する。"""
    by_id = {e.id: e for e in events}

    for rule in overrides.get("merge") or []:
        keep, remove = by_id.get(rule.get("keep", "")), by_id.get(rule.get("remove", ""))
        if remove is None:
            continue
        if keep is not None and keep is not remove:
            keep.history.extend(remove.history)
            keep.add_history(today, f"統合：{remove.id} を統合（{rule.get('reason', '')}）")
        del by_id[remove.id]

    fixes = fixes_by_id(overrides)
    for event in by_id.values():
        fix = fixes.get(event.id)
        if fix:
            changed = apply_fix(event, fix, cfg_venues, cfg_categories)
            if changed:
                event.add_history(today, "人手修正：" + "・".join(changed))

    confirm_ids = {c["id"] for c in overrides.get("confirm") or [] if c.get("id")}
    for event in by_id.values():
        reason = is_excluded(event, overrides)
        if reason:
            if event.status != "excluded":
                event.status = "excluded"
                event.add_history(today, f"除外：{reason}")
            continue
        if event.status == "excluded":
            # 除外ルールが削除された
            event.status = "unchanged"
            event.add_history(today, "除外解除")
        if event.id in confirm_ids and event.status == "needs_review":
            event.status = "unchanged"
            event.add_history(today, "確認済み")

    return list(by_id.values())
