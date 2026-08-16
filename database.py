"""SQLite migration and persistence for Cosmorex."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from callsign import generate_kcm_code

DB_PATH = Path("cosmorex_survey.db")
PRE_V11_BACKUP_PATH = Path("cosmorex_survey.pre_v1_1_backup.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(connection, table):
        return set()
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _add_column(connection: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    if name not in _columns(connection, table):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _backup_existing_database() -> None:
    if DB_PATH.exists() and not PRE_V11_BACKUP_PATH.exists():
        shutil.copy2(DB_PATH, PRE_V11_BACKUP_PATH)


def init_db() -> None:
    _backup_existing_database()

    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL
            )
            """
        )

        for name, definition in (
            ("username", "TEXT"),
            ("full_name", "TEXT"),
            ("participant_number", "INTEGER"),
            ("callsign", "TEXT"),
            ("age_group", "TEXT"),
            ("field", "TEXT"),
            ("role", "TEXT"),
            ("level", "INTEGER NOT NULL DEFAULT 0"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ):
            _add_column(connection, "participants", name, definition)

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                protocol_code TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                questions_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                result_text TEXT,
                created_at TEXT NOT NULL,
                closed_at TEXT
            )
            """
        )
        _add_column(
            connection,
            "research_cycles",
            "cycle_type",
            "TEXT NOT NULL DEFAULT 'main'",
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cycle_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                question_index INTEGER NOT NULL,
                answer_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(cycle_id, telegram_id, question_index)
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cycle_answers_cycle_user
            ON cycle_answers(cycle_id, telegram_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_research_cycles_type_status
            ON research_cycles(cycle_type, status)
            """
        )
        connection.commit()

    repair_participants()


def repair_participants() -> None:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, participant_number FROM participants ORDER BY id"
        ).fetchall()
        used: set[int] = set()
        next_number = 1

        for row in rows:
            number = row["participant_number"]
            if not isinstance(number, int) or number < 1 or number in used:
                while next_number in used:
                    next_number += 1
                number = next_number
            used.add(number)
            next_number = max(next_number, number + 1)
            connection.execute(
                """
                UPDATE participants
                SET participant_number=?, callsign=?, level=COALESCE(level, 0),
                    created_at=COALESCE(created_at, ?), updated_at=COALESCE(updated_at, ?)
                WHERE id=?
                """,
                (number, generate_kcm_code(number), _now(), _now(), row["id"]),
            )
        connection.commit()


def get_or_create_participant(telegram_id: int, username: str | None, full_name: str) -> dict[str, Any]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM participants WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone()
        if row:
            connection.execute(
                "UPDATE participants SET username=?, full_name=?, updated_at=? WHERE telegram_id=?",
                (username, full_name, _now(), telegram_id),
            )
            connection.commit()
            return dict(connection.execute(
                "SELECT * FROM participants WHERE telegram_id=?",
                (telegram_id,),
            ).fetchone())

        number = int(connection.execute(
            "SELECT COALESCE(MAX(participant_number), 0) + 1 AS number FROM participants"
        ).fetchone()["number"])
        connection.execute(
            """
            INSERT INTO participants (
                telegram_id, username, full_name, participant_number, callsign,
                level, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (telegram_id, username, full_name, number, generate_kcm_code(number), _now(), _now()),
        )
        connection.commit()
        return dict(connection.execute(
            "SELECT * FROM participants WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone())


def get_participant(telegram_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM participants WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone()
        return dict(row) if row else None


def update_participant(telegram_id: int, **values: Any) -> None:
    allowed = {"age_group", "field", "role", "level"}
    data = {key: value for key, value in values.items() if key in allowed}
    if not data:
        return
    data["updated_at"] = _now()
    with _connect() as connection:
        connection.execute(
            "UPDATE participants SET "
            + ", ".join(f"{key}=?" for key in data)
            + " WHERE telegram_id=?",
            [*data.values(), telegram_id],
        )
        connection.commit()


def ensure_default_cycle(code: str, title: str, questions: tuple[str, ...]) -> None:
    ensure_cycle(code, title, questions, cycle_type="main")


def ensure_cycle(
    code: str,
    title: str,
    questions: tuple[str, ...] | list[str],
    *,
    cycle_type: str,
) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO research_cycles (
                protocol_code, title, questions_json, status, created_at, cycle_type
            ) VALUES (?, ?, ?, 'open', ?, ?)
            """,
            (code, title, json.dumps(list(questions), ensure_ascii=False), _now(), cycle_type),
        )
        connection.commit()


def _decode_cycle(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    cycle = dict(row)
    cycle["questions"] = json.loads(cycle.pop("questions_json"))
    return cycle


def get_cycle(cycle_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        return _decode_cycle(connection.execute(
            "SELECT * FROM research_cycles WHERE id=?",
            (cycle_id,),
        ).fetchone())


def get_cycle_by_code(code: str) -> dict[str, Any] | None:
    with _connect() as connection:
        return _decode_cycle(connection.execute(
            "SELECT * FROM research_cycles WHERE protocol_code=?",
            (code.strip(),),
        ).fetchone())


def get_active_main_cycle() -> dict[str, Any] | None:
    with _connect() as connection:
        return _decode_cycle(connection.execute(
            """
            SELECT * FROM research_cycles
            WHERE cycle_type='main' AND status='open'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone())


def get_latest_main_cycle() -> dict[str, Any] | None:
    with _connect() as connection:
        return _decode_cycle(connection.execute(
            """
            SELECT * FROM research_cycles
            WHERE cycle_type='main'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone())


def list_parallel_cycles(*, status: str | None = None) -> list[dict[str, Any]]:
    with _connect() as connection:
        if status is None:
            rows = connection.execute(
                """
                SELECT * FROM research_cycles
                WHERE cycle_type='parallel'
                ORDER BY id ASC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM research_cycles
                WHERE cycle_type='parallel' AND status=?
                ORDER BY id ASC
                """,
                (status,),
            ).fetchall()
        return [_decode_cycle(row) for row in rows if row]


def list_open_parallel_cycles() -> list[dict[str, Any]]:
    return list_parallel_cycles(status="open")


# Compatibility with the previous version.
def get_active_cycle() -> dict[str, Any] | None:
    return get_active_main_cycle()


def get_latest_cycle() -> dict[str, Any] | None:
    return get_latest_main_cycle()


def _clean_cycle_input(code: str, title: str, questions: list[str]) -> tuple[str, str, list[str]]:
    clean_code = code.strip()
    clean_title = title.strip()
    clean_questions = [question.strip() for question in questions if question.strip()]
    if not clean_code or not clean_title or not clean_questions:
        raise ValueError("Код, название и хотя бы один вопрос обязательны.")
    return clean_code, clean_title, clean_questions


def create_main_cycle(code: str, title: str, questions: list[str]) -> int:
    clean_code, clean_title, clean_questions = _clean_cycle_input(code, title, questions)
    with _connect() as connection:
        connection.execute(
            """
            UPDATE research_cycles
            SET status='archived', closed_at=COALESCE(closed_at, ?)
            WHERE cycle_type='main' AND status='open'
            """,
            (_now(),),
        )
        cursor = connection.execute(
            """
            INSERT INTO research_cycles (
                protocol_code, title, questions_json, status, created_at, cycle_type
            ) VALUES (?, ?, ?, 'open', ?, 'main')
            """,
            (clean_code, clean_title, json.dumps(clean_questions, ensure_ascii=False), _now()),
        )
        connection.commit()
        return int(cursor.lastrowid)


def create_parallel_cycle(code: str, title: str, questions: list[str]) -> int:
    clean_code, clean_title, clean_questions = _clean_cycle_input(code, title, questions)
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO research_cycles (
                protocol_code, title, questions_json, status, created_at, cycle_type
            ) VALUES (?, ?, ?, 'open', ?, 'parallel')
            """,
            (clean_code, clean_title, json.dumps(clean_questions, ensure_ascii=False), _now()),
        )
        connection.commit()
        return int(cursor.lastrowid)


def create_cycle(code: str, title: str, questions: list[str]) -> int:
    return create_main_cycle(code, title, questions)


def save_answer(cycle_id: int, telegram_id: int, question_index: int, answer_text: str) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO cycle_answers (
                cycle_id, telegram_id, question_index, answer_text, created_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cycle_id, telegram_id, question_index)
            DO UPDATE SET answer_text=excluded.answer_text, created_at=excluded.created_at
            """,
            (cycle_id, telegram_id, question_index, answer_text, _now()),
        )
        connection.commit()


def get_user_answer_count(cycle_id: int, telegram_id: int) -> int:
    with _connect() as connection:
        return int(connection.execute(
            "SELECT COUNT(*) AS count FROM cycle_answers WHERE cycle_id=? AND telegram_id=?",
            (cycle_id, telegram_id),
        ).fetchone()["count"])


def is_cycle_completed_by_user(cycle: dict[str, Any], telegram_id: int) -> bool:
    return get_user_answer_count(cycle["id"], telegram_id) >= len(cycle["questions"])


def count_completed_parallel_cycles(telegram_id: int) -> int:
    count = 0
    for cycle in list_parallel_cycles():
        if is_cycle_completed_by_user(cycle, telegram_id):
            count += 1
    return count


def delete_user_answers(cycle_id: int, telegram_id: int) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM cycle_answers WHERE cycle_id=? AND telegram_id=?",
            (cycle_id, telegram_id),
        )
        connection.commit()
        return int(cursor.rowcount)


def get_cycle_stats(cycle_id: int) -> dict[str, int]:
    with _connect() as connection:
        participants = connection.execute(
            "SELECT COUNT(DISTINCT telegram_id) AS count FROM cycle_answers WHERE cycle_id=?",
            (cycle_id,),
        ).fetchone()["count"]
        answers = connection.execute(
            "SELECT COUNT(*) AS count FROM cycle_answers WHERE cycle_id=?",
            (cycle_id,),
        ).fetchone()["count"]
        return {"participants": int(participants or 0), "answers": int(answers or 0)}


def close_main_cycle(result_text: str) -> bool:
    cycle = get_active_main_cycle()
    if not cycle:
        return False
    with _connect() as connection:
        connection.execute(
            "UPDATE research_cycles SET status='closed', result_text=?, closed_at=? WHERE id=?",
            (result_text.strip(), _now(), cycle["id"]),
        )
        connection.commit()
    return True


def close_cycle_by_code(code: str, result_text: str) -> bool:
    cycle = get_cycle_by_code(code)
    if not cycle or cycle["status"] != "open":
        return False
    with _connect() as connection:
        connection.execute(
            "UPDATE research_cycles SET status='closed', result_text=?, closed_at=? WHERE id=?",
            (result_text.strip(), _now(), cycle["id"]),
        )
        connection.commit()
    return True


def close_active_cycle(result_text: str) -> bool:
    return close_main_cycle(result_text)


def reopen_latest_main_cycle() -> bool:
    cycle = get_latest_main_cycle()
    if not cycle:
        return False
    with _connect() as connection:
        connection.execute(
            "UPDATE research_cycles SET status='open', closed_at=NULL WHERE id=?",
            (cycle["id"],),
        )
        connection.commit()
    return True


def reopen_latest_cycle() -> bool:
    return reopen_latest_main_cycle()


def count_participants() -> int:
    with _connect() as connection:
        return int(connection.execute(
            "SELECT COUNT(*) AS count FROM participants"
        ).fetchone()["count"])


def export_cycle_rows(cycle_id: int) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT p.callsign, p.full_name, p.username, p.age_group, p.field, p.role,
                   a.question_index, a.answer_text, a.created_at
            FROM cycle_answers AS a
            LEFT JOIN participants AS p ON p.telegram_id=a.telegram_id
            WHERE a.cycle_id=?
            ORDER BY p.participant_number, a.question_index
            """,
            (cycle_id,),
        ).fetchall()
        return [dict(row) for row in rows]
