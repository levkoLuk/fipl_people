"""Загрузка переменных окружения из файла ``.env``.

Проект не использует сторонние библиотеки (``python-dotenv``, ``django-environ``),
поэтому простой разборщик ``KEY=VALUE`` реализован здесь. Правила:

* файл читается один раз при импорте :mod:`config.settings`;
* путь по умолчанию — ``<BASE_DIR>/.env``, переопределяется переменной
  ``DJANGO_ENV_FILE``;
* **настоящие переменные окружения имеют приоритет**: значения из файла
  подставляются только через :func:`os.environ.setdefault`;
* поддерживаются комментарии (``#``), пустые строки, префикс ``export``
  и кавычки вокруг значения;
* отсутствие файла не является ошибкой — конфигурация берётся из окружения.

Пример ``.env``::

    DJANGO_DEBUG=true
    DJANGO_SECRET_KEY=change-me
    POSTGRES_DB=fiplpeople
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE_VARIABLE = "DJANGO_ENV_FILE"
QUOTE_CHARS = ("'", '"')


def parse_env_file(path: Path) -> dict[str, str]:
    """Разбирает файл окружения и возвращает пары «ключ → значение»."""
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in QUOTE_CHARS:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env_file(base_dir: Path) -> Path | None:
    """Подгружает ``.env`` в :data:`os.environ`.

    :param base_dir: корень проекта, относительно которого ищется ``.env``.
    :returns: путь загруженного файла или ``None``, если файла нет.
    """
    override = os.getenv(ENV_FILE_VARIABLE)
    path = Path(override) if override else Path(base_dir) / ".env"
    if not path.is_file():
        return None
    for key, value in parse_env_file(path).items():
        os.environ.setdefault(key, value)
    return path
