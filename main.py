"""Cosmorex v3.2 with one main survey and parallel background cycles."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
from pathlib import Path
from typing import BinaryIO, Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramConflictError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    CallbackQuery,
    FSInputFile,
    Message,
    ReplyKeyboardRemove,
    User,
)

import database as db
from admin_handlers import admin_router, is_admin, send_admin_panel
from callsign import get_crew_status
from keyboards import (
    age_keyboard,
    cancel_keyboard,
    field_keyboard,
    launch_screen_inline,
    main_menu_inline,
    parallel_cycles_inline,
    role_keyboard,
)
from survey import (
    ABOUT_TEXT,
    ActivationStates,
    AGE_GROUP_OPTIONS,
    BACK_BUTTON_TEXT,
    COMMUNITY_ROLES,
    CycleStates,
    DEFAULT_PARALLEL_CYCLES,
    FIELD_OPTIONS,
    HELP_TEXT,
    LAUNCH_SCREEN_TEXT,
    MISSION_CHRONICLE_TEXT,
    PRIVACY_TEXT,
    PROTOCOL_ID,
    PROTOCOL_TEXT,
    RESEARCH_QUESTIONS,
    RoleStates,
    WALLPAPER_CAPTION,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("cosmorex")
router = Router(name="main")

START_IMAGE = Path("assets/cosmorex_start.jpg")
WALLPAPER_IMAGE = Path("assets/cosmorex_wallpaper.jpg")
_LOCK_HANDLE: BinaryIO | None = None


def acquire_single_instance_lock() -> None:
    global _LOCK_HANDLE
    handle = Path(".cosmorex_bot.lock").open("wb")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        handle.close()
        raise RuntimeError(
            "В этом Replit уже запущена другая копия бота. Остановите второй Run, Shell или Deployment."
        ) from error
    _LOCK_HANDLE = handle


def ensure_participant(user: User) -> dict[str, Any]:
    return db.get_or_create_participant(user.id, user.username, user.full_name)


def is_activated(participant: dict[str, Any]) -> bool:
    return bool(participant.get("age_group") and participant.get("field"))


def profile_text(participant: dict[str, Any], user_id: int) -> str:
    symbol, status = get_crew_status(participant.get("level"))
    completed_parallel = db.count_completed_parallel_cycles(user_id)
    return (
        "KCM // КАРТОЧКА УЧАСТНИКА\n"
        "━━━━━━━━━━━━━━\n\n"
        f"{participant.get('callsign') or 'ПОЗЫВНОЙ НЕ НАЗНАЧЕН'}\n\n"
        f"{symbol} {status}\n\n"
        f"СФЕРА\n{participant.get('field') or 'не указана'}\n\n"
        f"РОЛЬ\n{participant.get('role') or 'не выбрана'}\n\n"
        f"ПАРАЛЛЕЛЬНЫХ ЦИКЛОВ ЗАВЕРШЕНО\n{completed_parallel}\n\n"
        "МАРШРУТ\n▼1 → ▲2 → ▶3 → 🔗4 → ⬡5 → ⭕6\n\n"
        "━━━━━━━━━━━━━━"
    )


async def send_launch_screen(
    target: Message,
    user: User,
    participant: dict[str, Any] | None = None,
) -> None:
    participant = participant or ensure_participant(user)
    symbol, status = get_crew_status(participant.get("level"))
    caption = (
        f"{LAUNCH_SCREEN_TEXT}\n\n"
        f"ПОЗЫВНОЙ: {participant['callsign']}\n"
        f"СТАТУС УЧАСТНИКА: {symbol} {status}"
    )
    markup = launch_screen_inline(is_activated(participant))
    if START_IMAGE.exists():
        await target.answer_photo(
            photo=FSInputFile(START_IMAGE),
            caption=caption,
            reply_markup=markup,
        )
    else:
        await target.answer(caption, reply_markup=markup)


async def send_main_menu(
    target: Message,
    user: User,
    participant: dict[str, Any] | None = None,
) -> None:
    participant = participant or ensure_participant(user)
    main_cycle = db.get_active_main_cycle()
    if main_cycle:
        status = f"ГЛАВНЫЙ ЗАПРОС: {main_cycle['protocol_code']} — {main_cycle['title']}"
    else:
        status = "ГЛАВНЫЙ ЗАПРОС ОЖИДАЕТСЯ. ПАРАЛЛЕЛЬНЫЕ ЦИКЛЫ ДОСТУПНЫ."
    await target.answer(
        "🧭 COSMOREX // КОМАНДНЫЙ МОДУЛЬ\n\n"
        f"ПОЗЫВНОЙ: {participant['callsign']}\n"
        f"{status}\n"
        "Выберите команду.",
        reply_markup=main_menu_inline(is_admin(user.id)),
    )


async def show_protocol(target: Message) -> None:
    main_cycle = db.get_latest_main_cycle()
    status = main_cycle["status"].upper() if main_cycle else "НЕ СОЗДАН"
    parallel_count = len(db.list_open_parallel_cycles())
    await target.answer(
        f"{PROTOCOL_TEXT}\n\n"
        f"СТАТУС ГЛАВНОГО ОПРОСА: {status}\n"
        f"ОТКРЫТЫХ ПАРАЛЛЕЛЬНЫХ ЦИКЛОВ: {parallel_count}"
    )


async def show_results(target: Message) -> None:
    cycle = db.get_latest_main_cycle()
    if not cycle or cycle["status"] != "closed" or not cycle.get("result_text"):
        await target.answer(
            "🔗 РЕЗУЛЬТАТ ГЛАВНОГО ОПРОСА ЗАБЛОКИРОВАН\n\n"
            "Главный запрос продолжается или ещё не был закрыт."
        )
        return
    await target.answer(
        f"🔗 РЕЗУЛЬТАТ ГЛАВНОГО ОПРОСА {cycle['protocol_code']}\n\n"
        f"{cycle['result_text']}"
    )


async def show_profile(target: Message, user: User) -> None:
    participant = ensure_participant(user)
    await target.answer(profile_text(participant, user.id))


async def show_wallpaper(target: Message) -> None:
    if not WALLPAPER_IMAGE.exists():
        await target.answer("Файл фона отсутствует в папке assets.")
        return
    await target.answer_document(
        document=FSInputFile(WALLPAPER_IMAGE, filename="cosmorex_wallpaper.jpg"),
        caption=WALLPAPER_CAPTION,
    )


async def begin_activation(target: Message, user: User, state: FSMContext) -> None:
    participant = ensure_participant(user)
    if is_activated(participant):
        await send_main_menu(target, user, participant)
        return
    db.update_participant(user.id, level=1)
    await target.answer(
        "▼1 АКТИВАЦИЯ ПОЗЫВНОГО\n\nПервый параметр — возрастная группа.",
        reply_markup=age_keyboard(),
    )
    await state.set_state(ActivationStates.age)


async def begin_role(target: Message, user: User, state: FSMContext) -> None:
    ensure_participant(user)
    await target.answer(
        "⬡ РОЛЬ В ЭКИПАЖЕ\n\nКем вы видите себя в Cosmorex?",
        reply_markup=role_keyboard(),
    )
    await state.set_state(RoleStates.choosing)


def _parallel_cycles_for_user(user_id: int) -> list[dict[str, Any]]:
    result = []
    for cycle in db.list_open_parallel_cycles():
        item = dict(cycle)
        item["completed"] = db.is_cycle_completed_by_user(cycle, user_id)
        result.append(item)
    return result


async def show_parallel_cycles(target: Message, user: User) -> None:
    ensure_participant(user)
    cycles = _parallel_cycles_for_user(user.id)
    if not cycles:
        await target.answer(
            "◌ ПАРАЛЛЕЛЬНЫЕ ЦИКЛЫ\n\n"
            "Сейчас дополнительных исследований нет. Ожидайте следующий сигнал."
        )
        return
    await target.answer(
        "◌ ПАРАЛЛЕЛЬНЫЕ ЦИКЛЫ\n\n"
        "Это исследования на время ожидания следующего главного запроса. "
        "Они не заменяют главный опрос и не смешиваются с его результатом.\n\n"
        "Галочка означает, что цикл уже завершён.",
        reply_markup=parallel_cycles_inline(cycles),
    )


async def begin_specific_cycle(
    target: Message,
    user: User,
    state: FSMContext,
    cycle: dict[str, Any],
) -> None:
    participant = ensure_participant(user)
    if not is_activated(participant):
        await target.answer("Сначала активируйте позывной на стартовом экране.")
        return
    if cycle["status"] != "open":
        await target.answer("Этот цикл уже закрыт.")
        return

    question_index = db.get_user_answer_count(cycle["id"], user.id)
    questions = cycle["questions"]
    cycle_kind = cycle.get("cycle_type", "main")

    if question_index >= len(questions):
        if cycle_kind == "main":
            await target.answer(
                "🔗 ГЛАВНЫЙ ЗАПРОС ВЫПОЛНЕН\n\n"
                "Ваши ответы сохранены. Пока система готовит следующий главный сигнал, "
                "можно продолжить работу в параллельных циклах."
            )
            await show_parallel_cycles(target, user)
        else:
            await target.answer(
                f"✓ ПАРАЛЛЕЛЬНЫЙ ЦИКЛ {cycle['protocol_code']} УЖЕ ЗАВЕРШЁН\n\n"
                "Вклад сохранён. Можно выбрать другое исследование."
            )
            await show_parallel_cycles(target, user)
        return

    await state.update_data(
        cycle_id=cycle["id"],
        cycle_type=cycle_kind,
        protocol_code=cycle["protocol_code"],
        question_index=question_index,
        questions=questions,
    )
    await state.set_state(CycleStates.answering)
    heading = "ГЛАВНЫЙ ОПРОС" if cycle_kind == "main" else "ПАРАЛЛЕЛЬНЫЙ ЦИКЛ"
    await target.answer(
        f"▶ {heading}\n"
        f"ПРОТОКОЛ {cycle['protocol_code']}\n"
        f"{cycle['title']}\n\n"
        f"ВОПРОС {question_index + 1}/{len(questions)}\n"
        f"{questions[question_index]}",
        reply_markup=cancel_keyboard(),
    )


async def begin_main_cycle(target: Message, user: User, state: FSMContext) -> None:
    cycle = db.get_active_main_cycle()
    if not cycle:
        await target.answer(
            "НОВОГО ГЛАВНОГО ЗАПРОСА ПОКА НЕТ\n\n"
            "Пока система готовит следующий сигнал, доступны параллельные циклы."
        )
        await show_parallel_cycles(target, user)
        return
    await begin_specific_cycle(target, user, state, cycle)


async def begin_parallel_cycle(
    target: Message,
    user: User,
    state: FSMContext,
    cycle_id: int,
) -> None:
    cycle = db.get_cycle(cycle_id)
    if not cycle or cycle.get("cycle_type") != "parallel":
        await target.answer("Параллельный цикл не найден.")
        return
    await begin_specific_cycle(target, user, state, cycle)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.clear()
    await sync_chat_commands(message.bot, message.chat.id)
    participant = ensure_participant(message.from_user)
    await message.answer(
        "◀ СТАРТОВЫЙ КОМПЛЕКС АКТИВИРОВАН",
        reply_markup=ReplyKeyboardRemove(),
    )
    await send_launch_screen(message, message.from_user, participant)


@router.message(Command("menu"))
async def menu_command(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.clear()
    await sync_chat_commands(message.bot, message.chat.id)
    await message.answer("Интерфейс синхронизирован.", reply_markup=ReplyKeyboardRemove())
    await send_main_menu(message, message.from_user)


@router.message(Command("chronicle"))
async def chronicle_command(message: Message) -> None:
    await message.answer(MISSION_CHRONICLE_TEXT)


@router.message(Command("wallpaper"))
async def wallpaper_command(message: Message) -> None:
    await show_wallpaper(message)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.callback_query(F.data.startswith("launch:"))
async def launch_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    action = callback.data.split(":", 1)[1]
    target = callback.message
    user = callback.from_user
    if action == "enter":
        await begin_activation(target, user, state)
    elif action == "protocol":
        await show_protocol(target)
    elif action == "profile":
        await show_profile(target, user)
    elif action == "chronicle":
        await target.answer(MISSION_CHRONICLE_TEXT)
    elif action == "wallpaper":
        await show_wallpaper(target)


@router.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    action = callback.data.split(":", 1)[1]
    target = callback.message
    user = callback.from_user
    ensure_participant(user)

    if action == "root":
        await send_main_menu(target, user)
    elif action in {"cycle", "main_cycle"}:
        await begin_main_cycle(target, user, state)
    elif action == "parallel":
        await show_parallel_cycles(target, user)
    elif action == "protocol":
        await show_protocol(target)
    elif action == "results":
        await show_results(target)
    elif action == "profile":
        await show_profile(target, user)
    elif action == "role":
        await begin_role(target, user, state)
    elif action == "rocket":
        await send_launch_screen(target, user)
    elif action == "chronicle":
        await target.answer(MISSION_CHRONICLE_TEXT)
    elif action == "wallpaper":
        await show_wallpaper(target)
    elif action == "privacy":
        await target.answer(PRIVACY_TEXT)
    elif action == "about":
        await target.answer(ABOUT_TEXT)
    elif action == "admin":
        await send_admin_panel(target, user_id=user.id)


@router.callback_query(F.data.startswith("parallel:"))
async def parallel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    try:
        cycle_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.message.answer("Некорректный номер цикла.")
        return
    await begin_parallel_cycle(callback.message, callback.from_user, state, cycle_id)


@router.message(Command("protocol"))
async def protocol_command(message: Message) -> None:
    await show_protocol(message)


@router.message(Command("profile"))
async def profile_command(message: Message) -> None:
    if message.from_user:
        await show_profile(message, message.from_user)


@router.message(Command("results"))
async def results_command(message: Message) -> None:
    await show_results(message)


@router.message(Command("role"))
async def role_command(message: Message, state: FSMContext) -> None:
    if message.from_user:
        await begin_role(message, message.from_user, state)


@router.message(Command("cycle"))
async def cycle_command(message: Message, state: FSMContext) -> None:
    if message.from_user:
        await begin_main_cycle(message, message.from_user, state)


@router.message(Command("parallel"))
async def parallel_command(message: Message) -> None:
    if message.from_user:
        await show_parallel_cycles(message, message.from_user)


@router.message(ActivationStates.age)
async def activation_age(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if text == BACK_BUTTON_TEXT:
        await state.clear()
        await message.answer("Активация приостановлена.", reply_markup=ReplyKeyboardRemove())
        await send_launch_screen(message, message.from_user)
        return
    if text not in AGE_GROUP_OPTIONS:
        await message.answer("Выберите вариант кнопкой.", reply_markup=age_keyboard())
        return
    db.update_participant(message.from_user.id, age_group=text, level=1)
    await message.answer(
        "▼1 СИГНАЛ ПРИНЯТ\n\nУкажите основную сферу опыта или интереса.",
        reply_markup=field_keyboard(),
    )
    await state.set_state(ActivationStates.field)


@router.message(ActivationStates.field)
async def activation_field(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if text == BACK_BUTTON_TEXT:
        await state.set_state(ActivationStates.age)
        await message.answer("Возврат к предыдущему параметру.", reply_markup=age_keyboard())
        return
    if text not in FIELD_OPTIONS:
        await message.answer("Выберите вариант кнопкой.", reply_markup=field_keyboard())
        return
    db.update_participant(message.from_user.id, field=text, level=2)
    await state.clear()
    participant = db.get_participant(message.from_user.id)
    await message.answer(
        "▲2 ПЕРЕХОД ЗАФИКСИРОВАН\n\n"
        f"Активация завершена.\nПозывной: {participant['callsign']}",
        reply_markup=ReplyKeyboardRemove(),
    )
    await send_main_menu(message, message.from_user, participant)


@router.message(RoleStates.choosing)
async def choose_role(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if text == BACK_BUTTON_TEXT:
        await state.clear()
        await message.answer("Выбор роли отменён.", reply_markup=ReplyKeyboardRemove())
        await send_main_menu(message, message.from_user)
        return
    if text not in COMMUNITY_ROLES:
        await message.answer("Выберите роль кнопкой.", reply_markup=role_keyboard())
        return
    db.update_participant(message.from_user.id, role=text, level=3)
    await state.clear()
    await message.answer(
        f"▶3 РОЛЬ ЗАФИКСИРОВАНА\n\n{text}",
        reply_markup=ReplyKeyboardRemove(),
    )
    await send_main_menu(message, message.from_user)


@router.message(CycleStates.answering)
async def cycle_answer(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if text == BACK_BUTTON_TEXT:
        await state.clear()
        await message.answer(
            "Цикл приостановлен. Уже сохранённые ответы не потеряны.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await send_main_menu(message, message.from_user)
        return
    if len(text) < 2:
        await message.answer("Сформулируйте ответ подробнее.")
        return

    data = await state.get_data()
    cycle_id = int(data["cycle_id"])
    cycle_type = str(data.get("cycle_type", "main"))
    protocol_code = str(data.get("protocol_code", ""))
    question_index = int(data["question_index"])
    questions = list(data["questions"])

    db.save_answer(cycle_id, message.from_user.id, question_index, text)
    question_index += 1

    if question_index >= len(questions):
        await state.clear()
        if cycle_type == "main":
            db.update_participant(message.from_user.id, level=4)
            await message.answer(
                "🔗 ГЛАВНЫЙ ЗАПРОС ВЫПОЛНЕН\n\n"
                "Ответы приняты и скрыты до закрытия главного опроса. "
                "Пока система готовит следующий запрос, доступны параллельные циклы.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await show_parallel_cycles(message, message.from_user)
        else:
            await message.answer(
                f"✓ ПАРАЛЛЕЛЬНЫЙ ЦИКЛ {protocol_code} ЗАВЕРШЁН\n\n"
                "Вклад зафиксирован. Можно выбрать следующий параллельный цикл "
                "или вернуться в командный модуль.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await show_parallel_cycles(message, message.from_user)
        return

    await state.update_data(question_index=question_index)
    await message.answer(
        "ОТВЕТ ПРИНЯТ\n\n"
        f"ВОПРОС {question_index + 1}/{len(questions)}\n"
        f"{questions[question_index]}",
        reply_markup=cancel_keyboard(),
    )


@router.message()
async def fallback(message: Message) -> None:
    if message.from_user:
        ensure_participant(message.from_user)
    await message.answer("Команда не распознана. Откройте /menu.")


def command_list() -> list[BotCommand]:
    return [
        BotCommand(command="start", description="Стартовый комплекс"),
        BotCommand(command="menu", description="Командный модуль"),
        BotCommand(command="protocol", description="Устройство исследований"),
        BotCommand(command="cycle", description="Главный опрос"),
        BotCommand(command="parallel", description="Параллельные циклы"),
        BotCommand(command="profile", description="KCM-профиль"),
        BotCommand(command="role", description="Роль в экипаже"),
        BotCommand(command="results", description="Результат главного опроса"),
        BotCommand(command="chronicle", description="Хроника миссии"),
        BotCommand(command="wallpaper", description="Фон Cosmorex"),
        BotCommand(command="help", description="Список команд"),
        BotCommand(command="admin", description="Командный центр"),
    ]


async def set_commands(bot: Bot) -> None:
    commands = command_list()
    scope = BotCommandScopeDefault()
    await bot.set_my_commands(commands, scope=scope)
    await bot.set_my_commands(commands, scope=scope, language_code="ru")


async def sync_chat_commands(bot: Bot, chat_id: int) -> None:
    commands = command_list()
    scope = BotCommandScopeChat(chat_id=chat_id)
    await bot.set_my_commands(commands, scope=scope)
    await bot.set_my_commands(commands, scope=scope, language_code="ru")


async def run_bot() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN отсутствует в Replit Secrets.")

    acquire_single_instance_lock()
    db.init_db()
    db.ensure_default_cycle(PROTOCOL_ID, "Первый главный опрос", RESEARCH_QUESTIONS)
    for code, title, questions in DEFAULT_PARALLEL_CYCLES:
        db.ensure_cycle(code, title, questions, cycle_type="parallel")

    bot = Bot(token=token)
    dispatcher = Dispatcher()
    dispatcher.include_router(admin_router)
    dispatcher.include_router(router)

    await bot.delete_webhook(drop_pending_updates=False)
    await set_commands(bot)
    logger.info("Cosmorex v3.2 multicycle started")
    await dispatcher.start_polling(
        bot,
        allowed_updates=dispatcher.resolve_used_update_types(),
    )


def main() -> None:
    try:
        asyncio.run(run_bot())
    except TelegramConflictError:
        logger.error(
            "Telegram уже получает обновления другой копией этого бота. "
            "Остановите второй Run, Shell или Deployment."
        )
    except KeyboardInterrupt:
        logger.info("Cosmorex stopped")


if __name__ == "__main__":
    main()
