"""Только сборка inline-кнопок. Ни данных, ни сети, ни логики.

callback_data держим короткими: удаление IP — по индексу (mon:rm:3),
а не упаковкой адресов в 64 байта.
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Сканировать", callback_data="scan:start")
    kb.button(text="🕓 История", callback_data="hist:show")
    kb.button(text="📡 Мои IP", callback_data="mon:list")
    kb.button(text="🛰 Прокси", callback_data="px:list")
    kb.button(text="❓ Помощь", callback_data="help")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def back() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Меню", callback_data="menu")
    return kb.as_markup()


def cancel_scan() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⛔ Отмена", callback_data="scan:cancel")
    return kb.as_markup()


def history_actions() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Очистить историю", callback_data="hist:clear")
    kb.button(text="⬅️ Меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def myips(items: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for index, item in enumerate(items):
        kb.button(text=f"❌ {item.get('ip', '')}", callback_data=f"mon:rm:{index}")
    kb.button(text="🔄 Проверить сейчас", callback_data="mon:check")
    kb.button(text="➕ Добавить IP", callback_data="mon:add")
    kb.button(text="⬅️ Меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def confirm(yes_callback: str, no_callback: str = "menu") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data=yes_callback)
    kb.button(text="↩️ Нет", callback_data=no_callback)
    kb.adjust(2)
    return kb.as_markup()


def admin_menu(settings: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⚙️ Лимит пингов: {settings['ping_limit']}", callback_data="adm:limit")
    kb.button(text="🌍 Прокси", callback_data="adm:proxy")
    kb.button(text="📊 Статистика", callback_data="adm:stats")
    kb.button(text="🧹 Очистить всю историю", callback_data="adm:clear")
    kb.button(text="📣 Рассылка", callback_data="adm:bc")
    kb.button(text="⬅️ Меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def broadcast_cancel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⛔ Отменить рассылку", callback_data="adm:bc:cancel")
    return kb.as_markup()


def proxies_list(records: list[dict], is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for record in records:
        kb.button(text=f"❌ {record['host']}:{record['port']}", callback_data=f"px:rm:{record['id']}")
        if is_admin and record.get("status") == "up":
            kb.button(text=f"🔌 Подключить {record['host']}", callback_data=f"px:use:{record['id']}")
    kb.button(text="➕ Получить команду", callback_data="px:new")
    kb.button(text="⬅️ Меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()
