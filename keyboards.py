"""Cosmorex spacecraft-style controls and temporary reply keyboards."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from survey import (
    AGE_GROUP_OPTIONS,
    BACK_BUTTON_TEXT,
    COMMUNITY_ROLES,
    FIELD_OPTIONS,
)


def launch_screen_inline(is_activated: bool) -> InlineKeyboardMarkup:
    primary_text = (
        "🧭 КОМАНДНЫЙ МОДУЛЬ"
        if is_activated
        else "🚀 АКТИВИРОВАТЬ ПОЗЫВНОЙ"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=primary_text, callback_data="launch:enter")],
            [
                InlineKeyboardButton(text="📡 ПРОТОКОЛ", callback_data="launch:protocol"),
                InlineKeyboardButton(text="KCM ПРОФИЛЬ", callback_data="launch:profile"),
            ],
            [
                InlineKeyboardButton(text="🛰 ХРОНИКА", callback_data="launch:chronicle"),
                InlineKeyboardButton(text="🌌 ФОН", callback_data="launch:wallpaper"),
            ],
        ]
    )


def main_menu_inline(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="▶ ГЛАВНЫЙ ОПРОС", callback_data="menu:main_cycle")],
        [InlineKeyboardButton(text="◌ ПАРАЛЛЕЛЬНЫЕ ЦИКЛЫ", callback_data="menu:parallel")],
        [
            InlineKeyboardButton(text="📡 ПРОТОКОЛ", callback_data="menu:protocol"),
            InlineKeyboardButton(text="🔗 РЕЗУЛЬТАТ", callback_data="menu:results"),
        ],
        [
            InlineKeyboardButton(text="KCM ПРОФИЛЬ", callback_data="menu:profile"),
            InlineKeyboardButton(text="⬡ РОЛЬ", callback_data="menu:role"),
        ],
        [
            InlineKeyboardButton(text="🚀 СТАРТОВЫЙ КОМПЛЕКС", callback_data="menu:rocket"),
            InlineKeyboardButton(text="🛰 ХРОНИКА", callback_data="menu:chronicle"),
        ],
        [
            InlineKeyboardButton(text="🌌 ФОН", callback_data="menu:wallpaper"),
            InlineKeyboardButton(text="🛡 ДАННЫЕ", callback_data="menu:privacy"),
        ],
    ]
    if is_admin:
        rows.append(
            [InlineKeyboardButton(text="⚙ КОМАНДНЫЙ ЦЕНТР", callback_data="menu:admin")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parallel_cycles_inline(cycles: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for cycle in cycles:
        mark = "✓" if cycle.get("completed") else "◌"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {cycle['protocol_code']} — {cycle['title']}",
                    callback_data=f"parallel:{cycle['id']}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="← КОМАНДНЫЙ МОДУЛЬ", callback_data="menu:root")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 СТАТИСТИКА", callback_data="admin:stats"),
                InlineKeyboardButton(text="📥 CSV", callback_data="admin:export"),
            ],
            [
                InlineKeyboardButton(
                    text="🧪 СБРОСИТЬ МОИ ОТВЕТЫ",
                    callback_data="admin:reset_my_answers",
                )
            ],
            [InlineKeyboardButton(text="← КОМАНДНЫЙ МОДУЛЬ", callback_data="menu:root")],
        ]
    )


def _reply_keyboard(options: tuple[str, ...], placeholder: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=value)] for value in options]
        + [[KeyboardButton(text=BACK_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder=placeholder,
    )


def age_keyboard() -> ReplyKeyboardMarkup:
    return _reply_keyboard(AGE_GROUP_OPTIONS, "Возрастная группа")


def field_keyboard() -> ReplyKeyboardMarkup:
    return _reply_keyboard(FIELD_OPTIONS, "Сфера опыта")


def role_keyboard() -> ReplyKeyboardMarkup:
    return _reply_keyboard(COMMUNITY_ROLES, "Роль в экипаже")


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BACK_BUTTON_TEXT)]],
        resize_keyboard=True,
        input_field_placeholder="Введите ответ",
    )
