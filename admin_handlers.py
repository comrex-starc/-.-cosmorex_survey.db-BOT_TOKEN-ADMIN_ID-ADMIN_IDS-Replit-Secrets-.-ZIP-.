"""Administrative commands and inline panel."""

from __future__ import annotations

import csv
import os
import sqlite3
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message

import database as db
from keyboards import admin_menu_inline

admin_router = Router(name="admin")


def get_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "").strip() or os.getenv("ADMIN_ID", "").strip()
    result: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            continue
    return result


_get_admin_ids = get_admin_ids


def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids()


async def _deny_message(message: Message) -> None:
    await message.answer("Доступ к административному протоколу отсутствует.")


async def _deny_callback(callback: CallbackQuery) -> None:
    await callback.answer("Доступ отсутствует.", show_alert=True)


def _cycle_line(cycle: dict | None) -> str:
    if not cycle:
        return "Главный опрос сейчас не открыт."
    stats = db.get_cycle_stats(cycle["id"])
    return (
        f"Главный опрос: {cycle['protocol_code']} — {cycle['title']}\n"
        f"Статус: {cycle['status']}\n"
        f"Участников: {stats['participants']}\n"
        f"Ответов: {stats['answers']}"
    )


def _admin_panel_text() -> str:
    main_cycle = db.get_latest_main_cycle()
    parallel = db.list_open_parallel_cycles()
    parallel_lines = [
        f"{cycle['protocol_code']} — {cycle['title']}"
        for cycle in parallel
    ]
    parallel_text = "\n".join(parallel_lines) if parallel_lines else "Открытых параллельных циклов нет."

    return (
        "⚙ АДМИНИСТРАТИВНЫЙ ПРОТОКОЛ\n\n"
        f"Всего участников: {db.count_participants()}\n\n"
        f"{_cycle_line(main_cycle)}\n\n"
        "Параллельные циклы:\n"
        f"{parallel_text}\n\n"
        "Команды:\n"
        "/admin_new_main 002 | Название | Вопрос 1 | Вопрос 2\n"
        "/admin_new_parallel P002 | Название | Вопрос 1 | Вопрос 2\n"
        "/admin_close итог главного опроса\n"
        "/admin_close_parallel P002 | итог\n"
        "/admin_reopen\n"
        "/admin_export\n"
        "/admin_export P002"
    )


async def send_admin_panel(message: Message, user_id: int | None = None) -> None:
    effective_user_id = user_id
    if effective_user_id is None and message.from_user:
        effective_user_id = message.from_user.id
    if effective_user_id is None or not is_admin(effective_user_id):
        await _deny_message(message)
        return
    await message.answer(_admin_panel_text(), reply_markup=admin_menu_inline())


@admin_router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    await send_admin_panel(message)


@admin_router.message(Command("admin_stats"))
async def admin_stats(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await _deny_message(message)
        return
    await message.answer(_admin_panel_text())


def _parse_cycle_payload(message: Message) -> tuple[str, str, list[str]] | None:
    payload = (message.text or "").partition(" ")[2].strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 4:
        return None
    code, title, *questions = parts
    return code, title, questions


async def _create_cycle(message: Message, *, cycle_type: str) -> None:
    parsed = _parse_cycle_payload(message)
    if not parsed:
        command = "/admin_new_main" if cycle_type == "main" else "/admin_new_parallel"
        await message.answer(
            f"Формат:\n{command} 002 | Название | Вопрос 1 | Вопрос 2"
        )
        return
    code, title, questions = parsed
    try:
        if cycle_type == "main":
            db.create_main_cycle(code, title, questions)
        else:
            db.create_parallel_cycle(code, title, questions)
    except (ValueError, sqlite3.IntegrityError) as error:
        await message.answer(f"Цикл не создан: {error}")
        return
    kind = "главный опрос" if cycle_type == "main" else "параллельный цикл"
    await message.answer(f"Открыт {kind} {code}.\nВопросов: {len(questions)}")


@admin_router.message(Command("admin_new"))
@admin_router.message(Command("admin_new_main"))
async def admin_new_main(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await _deny_message(message)
        return
    await _create_cycle(message, cycle_type="main")


@admin_router.message(Command("admin_new_parallel"))
async def admin_new_parallel(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await _deny_message(message)
        return
    await _create_cycle(message, cycle_type="parallel")


@admin_router.message(Command("admin_close"))
async def admin_close(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await _deny_message(message)
        return
    result_text = (message.text or "").partition(" ")[2].strip()
    if not result_text:
        await message.answer("Пример:\n/admin_close Приоритет этапа — мобильная лаборатория.")
        return
    await message.answer(
        "Главный опрос закрыт. Результат опубликован."
        if db.close_main_cycle(result_text)
        else "Открытого главного опроса нет."
    )


@admin_router.message(Command("admin_close_parallel"))
async def admin_close_parallel(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await _deny_message(message)
        return
    payload = (message.text or "").partition(" ")[2].strip()
    code, separator, result_text = payload.partition("|")
    if not separator or not code.strip() or not result_text.strip():
        await message.answer("Пример:\n/admin_close_parallel P002 | итог параллельного цикла")
        return
    await message.answer(
        f"Параллельный цикл {code.strip()} закрыт."
        if db.close_cycle_by_code(code.strip(), result_text.strip())
        else "Открытый цикл с таким кодом не найден."
    )


@admin_router.message(Command("admin_reopen"))
async def admin_reopen(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await _deny_message(message)
        return
    await message.answer(
        "Последний главный опрос снова открыт."
        if db.reopen_latest_main_cycle()
        else "Главные опросы отсутствуют."
    )


async def _send_export(message: Message, code: str | None = None) -> None:
    cycle = db.get_cycle_by_code(code) if code else db.get_latest_main_cycle()
    if not cycle:
        await message.answer("Цикл не найден.")
        return
    rows = db.export_cycle_rows(cycle["id"])
    if not rows:
        await message.answer("В выбранном цикле пока нет ответов.")
        return
    path = Path(tempfile.gettempdir()) / f"cosmorex_{cycle['protocol_code']}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    await message.answer_document(
        FSInputFile(path),
        caption=f"Экспорт протокола {cycle['protocol_code']}",
    )


@admin_router.message(Command("admin_export"))
async def admin_export(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await _deny_message(message)
        return
    code = (message.text or "").partition(" ")[2].strip() or None
    await _send_export(message, code)


@admin_router.callback_query(F.data.startswith("admin:"))
async def admin_callback(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await _deny_callback(callback)
        return
    if not callback.message:
        await callback.answer()
        return
    action = callback.data.split(":", 1)[1]
    await callback.answer()
    if action == "stats":
        await callback.message.answer(_admin_panel_text())
        return
    if action == "export":
        await _send_export(callback.message)
        return
    if action == "reset_my_answers":
        cycle = db.get_active_main_cycle() or db.get_latest_main_cycle()
        if not cycle:
            await callback.message.answer("Главные опросы отсутствуют.")
            return
        deleted = db.delete_user_answers(cycle["id"], callback.from_user.id)
        await callback.message.answer(
            f"Удалено ваших ответов: {deleted}.\nГлавный опрос можно пройти заново."
        )
