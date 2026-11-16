"""Только форматирование текста. Одна точка, чтобы не дублировать в хендлерах."""
from __future__ import annotations

import html
import re
from datetime import datetime

MAX_TEXT = 3500  # лимит Telegram — 4096, берём с запасом


def esc(value) -> str:
    """Любой пользовательский текст — только через это (parse_mode=HTML)."""
    return html.escape(str(value))


def cut(text: str) -> str:
    if len(text) <= MAX_TEXT:
        return text
    return text[: MAX_TEXT - 15].rstrip() + "\n…(обрезано)"


def mask_proxy(url: str | None) -> str:
    """Показываем адрес прокси, но не пароль (он попадает в логи и в чат)."""
    if not url:
        return "нет"
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url)


def mention(uid: int, name: str | None) -> str:
    """HTML-упоминание: работает даже если у человека нет username."""
    return f'<a href="tg://user?id={uid}">{esc(name or "участник")}</a>'


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


PROXY_STATUS = {"waiting": "ждём запуска", "up": "работает", "down": "не отвечает", "expired": "заявка снята"}
PROXY_MARK = {"waiting": "⏳", "up": "✅", "down": "❌", "expired": "⌛"}


def proxy_invite(command: str) -> str:
    return (
        "🤝 Подними свой SOCKS5 для бота — одна команда на твоём сервере:\n\n"
        f"<code>{esc(command)}</code>\n\n"
        "Порт 1080 должен быть открыт снаружи (firewall / security group).\n"
        "Бот сам дождётся запуска и напишет в чат уведомлений, когда прокси заработает."
    )


def proxies_text(records: list[dict], is_admin: bool = False) -> str:
    if not records:
        return "🛰 Прокси пока нет. Взять команду: /get_proxy"
    lines = ["🛰 Прокси участников:"]
    for record in records:
        status = record.get("status", "waiting")
        owner = f" · {esc(record.get('owner_name') or record.get('owner'))}" if is_admin else ""
        lines.append(
            f"{PROXY_MARK.get(status, '?')} {esc(record['host'])}:{record['port']} — "
            f"{PROXY_STATUS.get(status, status)}{owner}"
        )
    lines.append("\n❌ — убрать прокси из списка.")
    return cut("\n".join(lines))
