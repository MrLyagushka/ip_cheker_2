"""Только форматирование текста. Одна точка, чтобы не дублировать в хендлерах."""
from __future__ import annotations

import html
from datetime import datetime

MAX_TEXT = 3500  # лимит Telegram — 4096, берём с запасом


def esc(value) -> str:
    """Любой пользовательский текст — только через это (parse_mode=HTML)."""
    return html.escape(str(value))


def cut(text: str) -> str:
    if len(text) <= MAX_TEXT:
        return text
    return text[: MAX_TEXT - 15].rstrip() + "\n…(обрезано)"


def icon(alive: bool) -> str:
    return "✅" if alive else "❌"


def scan_summary(label: str, kind: str, results: dict[str, bool], cancelled: bool = False) -> str:
    if kind == "host":
        alive = next(iter(results.values()), False)
        body = f"{icon(alive)} {esc(label)} — {'доступен' if alive else 'недоступен'}"
    else:
        alive_count = sum(1 for ok in results.values() if ok)
        body = (
            f"🌐 Сеть {esc(label)}\n"
            f"Доступны: {alive_count} из {len(results)} проверенных"
        )
    if cancelled:
        body += "\n⛔ Отменено: проверена только часть адресов"
    return body


def result_file(label: str, results: dict[str, bool]) -> str:
    alive_count = sum(1 for ok in results.values() if ok)
    lines = [f"{label} — доступны {alive_count} из {len(results)}", ""]
    lines += [f"{ip}\t{'alive' if ok else 'dead'}" for ip, ok in results.items()]
    return "\n".join(lines) + "\n"


def history_text(items: list[dict]) -> str:
    if not items:
        return "🕓 История пуста. Начни со /scan"
    lines = ["🕓 Последние сканы:"]
    for item in reversed(items[-20:]):  # свежие сверху
        kind = "сеть" if item.get("type") == "subnet" else "IP"
        lines.append(
            f"{esc(item.get('ts', ''))} · {kind} {esc(item.get('target', ''))} · "
            f"{item.get('up', 0)}/{item.get('total', 0)} доступны"
        )
    return cut("\n".join(lines))


def myips_text(items: list[dict]) -> str:
    if not items:
        return "📡 Список мониторинга пуст. Добавь: /watch 8.8.8.8"
    marks = {"up": "✅", "down": "❌", "unknown": "❔"}
    lines = ["📡 Твои IP (статус на последней проверке):"]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {marks.get(item.get('status'), '❔')} {esc(item.get('ip', ''))}")
    lines.append("\nНажми ❌, чтобы убрать адрес из списка.")
    return cut("\n".join(lines))


def check_text(results: dict[str, bool]) -> str:
    if not results:
        return "📡 Список пуст или проверка отменена"
    lines = ["🔎 Проверка сейчас:"]
    lines += [f"{icon(ok)} {esc(ip)}" for ip, ok in results.items()]
    return cut("\n".join(lines))


def changes_text(changes: dict[str, tuple[str, str]]) -> str:
    lines = ["🔔 Изменения доступности:"]
    for ip, (old, new) in changes.items():
        lines.append(f"{icon(new == 'up')} {esc(ip)}: {esc(old)} → {esc(new)}")
    lines.append(f"🕒 {datetime.now().strftime('%d.%m %H:%M')}")
    return cut("\n".join(lines))


def stats_text(users: dict, history: dict, tracked: dict, busy: int) -> str:
    scans = sum(len(items) for items in history.values())
    ips = sum(len(items) for items in tracked.values())
    return (
        "📊 Статистика\n"
        f"Пользователей: {len(users)}\n"
        f"Сканов в истории: {scans}\n"
        f"IP в мониторинге: {ips}\n"
        f"Сканов идёт сейчас: {busy}"
    )
