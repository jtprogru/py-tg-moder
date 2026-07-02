# -*- coding: utf-8 -*-
"""Dashboard pages: overview, per-chat analytics, users and the audit browser.

Every route requires an authenticated admin. Storage is synchronous, so all
queries go through ``asyncio.to_thread`` — same as the bot handlers.
"""

import asyncio
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from core import raid
from core.audit import AuditEvent
from core.storage import get_storage
from web.auth import make_csrf, require_admin
from web.templating import templates

router = APIRouter(dependencies=[Depends(require_admin)])

# Time ranges offered by the period filter, in days.
PERIODS = (7, 30, 90, 180, 365)

# Long ranges are charted in coarser buckets so the x-axis stays readable.
_GRANULARITY_LABELS = {"day": "по дням", "week": "по неделям", "month": "по месяцам"}
_BUCKET_COLUMNS = {"day": "День", "week": "Неделя (с)", "month": "Месяц"}

# Russian display names for audit events (also the audit-browser filter list).
EVENT_LABELS: dict[str, str] = {
    AuditEvent.BAN: "бан",
    AuditEvent.UNBAN: "разбан",
    AuditEvent.KICK: "кик",
    AuditEvent.MUTE: "мьют",
    AuditEvent.UNMUTE: "размьют",
    AuditEvent.WARN: "предупреждение",
    AuditEvent.UNWARN: "снятие предупреждения",
    AuditEvent.WARNS_CLEARED: "сброс предупреждений",
    AuditEvent.AUTO_BAN: "автобан",
    AuditEvent.AUTO_MUTE: "автомьют",
    AuditEvent.CAPTCHA_SHOWN: "капча показана",
    AuditEvent.CAPTCHA_PASSED: "капча пройдена",
    AuditEvent.CAPTCHA_FAILED: "капча провалена",
    AuditEvent.CAS_BAN: "CAS-бан",
    AuditEvent.FLOOD_MUTE: "мьют за флуд",
    AuditEvent.NEWCOMER_FILTERED: "фильтр новичка",
    AuditEvent.MEDIA_DELETED: "удаление медиа",
    AuditEvent.MEMBER_JOINED: "вступление",
    AuditEvent.MEMBER_LEFT: "выход",
    AuditEvent.COMPACTION_FORCED: "компактинг БД",
    AuditEvent.RAID_STARTED: "начало рейда",
    AuditEvent.RAID_ENDED: "конец рейда",
    AuditEvent.BACKUP_CREATED: "бэкап создан",
}

# Events that count as "moderation actions" in the headline tile and breakdown
# (informational events like joins or captcha_shown are not actions).
ACTION_EVENTS = (
    AuditEvent.BAN,
    AuditEvent.KICK,
    AuditEvent.MUTE,
    AuditEvent.WARN,
    AuditEvent.AUTO_BAN,
    AuditEvent.AUTO_MUTE,
    AuditEvent.CAS_BAN,
    AuditEvent.CAPTCHA_FAILED,
    AuditEvent.FLOOD_MUTE,
    AuditEvent.NEWCOMER_FILTERED,
    AuditEvent.MEDIA_DELETED,
)


def _clamp_period(days: int) -> int:
    return days if days in PERIODS else 30


def _day_range(days: int, now: int) -> list[str]:
    """The last ``days`` UTC days as YYYY-MM-DD, oldest first, today included."""
    today = datetime.fromtimestamp(now, tz=timezone.utc).date()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]


def _series_over(day_range: list[str], rows: list[dict], key: str = "count") -> list[int]:
    """Align sparse per-day rows to a continuous day range (missing days = 0)."""
    by_day = {row["day"]: row[key] for row in rows}
    return [by_day.get(day, 0) for day in day_range]


def _granularity(days: int) -> str:
    return "day" if days <= 31 else "week" if days <= 180 else "month"


def _bucketize(day_range: list[str], series: dict[str, list[int]], granularity: str) -> tuple[list[str], dict[str, list[int]]]:
    """Sum per-day series into week/month buckets for long periods.

    Weekly buckets are labeled by their Monday, monthly by YYYY-MM; the edge
    buckets may cover fewer days than a full week/month.
    """
    if granularity == "day":
        return day_range, series
    labels: list[str] = []
    index: dict[str, int] = {}
    positions: list[int] = []
    for day in day_range:
        if granularity == "week":
            d = date.fromisoformat(day)
            key = (d - timedelta(days=d.weekday())).isoformat()
        else:
            key = day[:7]
        if key not in index:
            index[key] = len(labels)
            labels.append(key)
        positions.append(index[key])
    bucketed = {name: [0] * len(labels) for name in series}
    for name, values in series.items():
        for position, value in zip(positions, values):
            bucketed[name][position] += value
    return labels, bucketed


async def _chat_title(request: Request, chat_id: int) -> str:
    """Best-effort chat title via the Bot API, cached for the process lifetime."""
    cache = request.app.state.chat_titles
    if chat_id in cache:
        return cache[chat_id]
    title = str(chat_id)
    application = request.app.state.application
    if application is not None:
        try:
            chat = await application.bot.get_chat(chat_id)
            title = chat.title or chat.username or str(chat_id)
        except Exception:  # unreachable chat, not initialized, network — show the id
            return title
    cache[chat_id] = title
    return title


def _display_names(storage, user_ids: list[int]) -> dict[int, str]:
    """user_id -> "@username" or the bare id when the name was never cached."""
    known = storage.usernames_map(user_ids)
    return {uid: f"@{known[uid]}" if uid in known else str(uid) for uid in user_ids}


@router.get("/", response_class=HTMLResponse)
async def overview(request: Request) -> Response:
    """All chats with their headline numbers; jumps straight in for one chat."""
    storage = get_storage()
    now = int(time.time())
    chat_ids = await asyncio.to_thread(storage.list_chats)
    if len(chat_ids) == 1:
        return RedirectResponse(f"/chats/{chat_ids[0]}", status_code=303)

    week_ago_day = _day_range(7, now)[0]
    chats = []
    for chat_id in chat_ids:
        totals = await asyncio.to_thread(storage.member_totals, chat_id)
        messages_7d = sum(row["count"] for row in await asyncio.to_thread(storage.message_series, chat_id, week_ago_day))
        audit_7d = await asyncio.to_thread(storage.audit_totals, chat_id, now - 7 * 86400)
        actions_7d = sum(audit_7d.get(event, 0) for event in ACTION_EVENTS)
        chats.append(
            {
                "id": chat_id,
                "title": await _chat_title(request, chat_id),
                "members": totals["members"],
                "messages_7d": messages_7d,
                "actions_7d": actions_7d,
            }
        )
    return templates.TemplateResponse(request, "overview.html", {"chats": chats})


@router.get("/chats/{chat_id}", response_class=HTMLResponse)
async def chat_page(request: Request, chat_id: int, days: int = Query(30), admin: int = Depends(require_admin)) -> Response:
    """Per-chat analytics: stat tiles, activity charts and top lists."""
    storage = get_storage()
    days = _clamp_period(days)
    now = int(time.time())
    since_ts = now - days * 86400
    day_range = _day_range(days, now)

    totals = await asyncio.to_thread(storage.member_totals, chat_id)
    message_rows = await asyncio.to_thread(storage.message_series, chat_id, day_range[0])
    audit_rows = await asyncio.to_thread(storage.audit_series, chat_id, since_ts)
    audit_totals = await asyncio.to_thread(storage.audit_totals, chat_id, since_ts)
    top_posters = await asyncio.to_thread(storage.top_posters, chat_id, day_range[0], 10)
    top_warned = await asyncio.to_thread(storage.top_warned, chat_id, since_ts, 10)

    joins = _series_over(day_range, [r for r in audit_rows if r["event"] == AuditEvent.MEMBER_JOINED])
    leaves = _series_over(day_range, [r for r in audit_rows if r["event"] == AuditEvent.MEMBER_LEFT])

    captcha = {
        "shown": audit_totals.get(AuditEvent.CAPTCHA_SHOWN, 0),
        "passed": audit_totals.get(AuditEvent.CAPTCHA_PASSED, 0),
        "failed": audit_totals.get(AuditEvent.CAPTCHA_FAILED, 0),
    }
    resolved = captcha["passed"] + captcha["failed"]
    captcha["rate"] = round(100 * captcha["passed"] / resolved) if resolved else None

    actions = sorted(
        ({"label": EVENT_LABELS[event], "count": audit_totals[event]} for event in ACTION_EVENTS if audit_totals.get(event)),
        key=lambda item: item["count"],
        reverse=True,
    )

    granularity = _granularity(days)
    labels, bucketed = _bucketize(
        day_range,
        {"messages": _series_over(day_range, message_rows), "joins": joins, "leaves": leaves},
        granularity,
    )

    names = await asyncio.to_thread(_display_names, storage, [row["user_id"] for row in top_posters + top_warned])
    context = {
        "chat_id": chat_id,
        "chat_title": await _chat_title(request, chat_id),
        "csrf": make_csrf(admin),
        "raid_active": raid.is_raid_active(chat_id),
        "raids_total": audit_totals.get(AuditEvent.RAID_STARTED, 0),
        "days": days,
        "periods": PERIODS,
        "totals": totals,
        "joins_total": sum(joins),
        "leaves_total": sum(leaves),
        "messages_total": sum(row["count"] for row in message_rows),
        "captcha": captcha,
        "actions": actions,
        "actions_total": sum(item["count"] for item in actions),
        "top_posters": [{**row, "name": names[row["user_id"]]} for row in top_posters],
        "top_warned": [{**row, "name": names[row["user_id"]]} for row in top_warned],
        "granularity_label": _GRANULARITY_LABELS[granularity],
        "bucket_column": _BUCKET_COLUMNS[granularity],
        "charts": {
            "days": labels,
            "messages": bucketed["messages"],
            "joins": bucketed["joins"],
            "leaves": bucketed["leaves"],
            "actions": {"labels": [a["label"] for a in actions], "counts": [a["count"] for a in actions]},
        },
    }
    return templates.TemplateResponse(request, "chat.html", context)


@router.get("/chats/{chat_id}/users/{user_id}", response_class=HTMLResponse)
async def user_page(
    request: Request,
    chat_id: int,
    user_id: int,
    days: int = Query(30),
    admin: int = Depends(require_admin),
) -> Response:
    """One user's history in a chat: activity, warns, mute state, audit trail."""
    storage = get_storage()
    days = _clamp_period(days)
    now = int(time.time())
    day_range = _day_range(days, now)

    member = await asyncio.to_thread(storage.get_member, chat_id, user_id)
    warns = list(reversed(await asyncio.to_thread(storage.list_warns, chat_id, user_id, True)))  # newest first
    mute = await asyncio.to_thread(storage.get_mute, chat_id, user_id)
    message_rows = await asyncio.to_thread(storage.user_message_series, chat_id, user_id, day_range[0])
    events = await asyncio.to_thread(storage.list_audit_events, chat_id, None, user_id, None, None, 25, 0)
    events_total = await asyncio.to_thread(storage.count_audit_events, chat_id, None, user_id)

    ids = {user_id} | {w["moderator_id"] for w in warns if w["moderator_id"]} | {e["actor_id"] for e in events if e["actor_id"]}
    names = await asyncio.to_thread(_display_names, storage, list(ids))

    granularity = _granularity(days)
    labels, bucketed = _bucketize(day_range, {"messages": _series_over(day_range, message_rows)}, granularity)

    context = {
        "chat_id": chat_id,
        "chat_title": await _chat_title(request, chat_id),
        "user_id": user_id,
        "user_name": names[user_id],
        "csrf": make_csrf(admin),
        "days": days,
        "periods": PERIODS,
        "member": member,
        "warns": warns,
        "active_warns": sum(1 for w in warns if w["deleted_at"] is None),
        "mute": mute,
        "mute_active": bool(mute) and (mute["until"] is None or mute["until"] > now),
        "messages_period": sum(row["count"] for row in message_rows),
        "events": events,
        "events_total": events_total,
        "names": names,
        "event_labels": EVENT_LABELS,
        "granularity_label": _GRANULARITY_LABELS[granularity],
        "bucket_column": _BUCKET_COLUMNS[granularity],
        "charts": {"days": labels, "messages": bucketed["messages"]},
    }
    return templates.TemplateResponse(request, "user.html", context)


@router.get("/chats/{chat_id}/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    chat_id: int,
    event: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    admin: int = Depends(require_admin),
) -> Response:
    """Filterable, paginated audit-log browser (htmx swaps the table in place)."""
    storage = get_storage()
    page_size = 50
    event = event if event in EVENT_LABELS else None

    events = await asyncio.to_thread(storage.list_audit_events, chat_id, event, user_id, None, None, page_size, (page - 1) * page_size)
    total = await asyncio.to_thread(storage.count_audit_events, chat_id, event, user_id)
    names = await asyncio.to_thread(
        _display_names, storage, list({e["user_id"] for e in events if e["user_id"]} | {e["actor_id"] for e in events if e["actor_id"]})
    )

    context = {
        "chat_id": chat_id,
        "chat_title": await _chat_title(request, chat_id),
        "csrf": make_csrf(admin),
        "events": events,
        "names": names,
        "event_labels": EVENT_LABELS,
        "filter_event": event or "",
        "filter_user_id": user_id,
        "page": page,
        "pages": max(1, -(-total // page_size)),
        "total": total,
    }
    template = "_audit_table.html" if request.headers.get("HX-Request") else "audit.html"
    return templates.TemplateResponse(request, template, context)
