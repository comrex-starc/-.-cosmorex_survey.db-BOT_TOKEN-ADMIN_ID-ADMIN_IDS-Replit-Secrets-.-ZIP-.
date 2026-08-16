"""Cosmorex callsign and participant status utilities."""

TRIANGLES = ("▲", "▶", "▼", "◀")


def to_triangle_base4(number: int, width: int = 4) -> str:
    """Convert a positive integer to the canonical triangle base-4 code."""
    value = max(1, int(number))
    digits: list[str] = []

    while value:
        value, remainder = divmod(value, 4)
        digits.append(TRIANGLES[remainder])

    while len(digits) < width:
        digits.append(TRIANGLES[0])

    return "".join(reversed(digits))


def generate_kcm_code(participant_number: int) -> str:
    """Return a permanent Cosmorex callsign."""
    return f"KCM-{to_triangle_base4(participant_number)}"


# Compatibility with previous project versions.
generate_ksm_code = generate_kcm_code


def get_crew_status(level: int | None) -> tuple[str, str]:
    statuses = {
        0: ("⚫0", "Вход в систему"),
        1: ("▼1", "Сигнал принят"),
        2: ("▲2", "Переход зафиксирован"),
        3: ("▶3", "Действие начато"),
        4: ("🔗4", "Связь установлена"),
        5: ("⬡5", "Модуль сформирован"),
        6: ("⭕6", "Среда создана"),
    }
    return statuses.get(int(level or 0), statuses[0])
