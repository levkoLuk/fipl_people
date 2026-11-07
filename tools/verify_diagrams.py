"""Сверка Mermaid ER-диаграмм с фактическими Django-моделями.

Скрипт читает файлы ``docs/diagrams/*.mmd`` и проверяет:

1. сущности соответствуют таблицам проекта (включая служебные таблицы Django);
2. каждая колонка существует в модели и имеет верный тип;
3. пометки ``PK`` / ``FK`` / ``UK`` соответствуют ограничениям модели;
4. пометка ``null:`` в комментарии соответствует ``null=True``;
5. все внешние ключи модели отражены линией связи;
6. каждая линия связи соответствует хотя бы одному внешнему ключу;
7. связи «многие ко многим» отражены строками ``m2m``;
8. базовая корректность синтаксиса (блоки, кавычки, объявления).

Соглашения о полноте:

* файл с комментарием ``%% verify: complete`` проверяется на наличие **всех**
  колонок каждой сущности;
* сущности, оформленные классом ``external``, считаются внешними заглушками:
  для них проверяются только объявленные колонки (диаграмма приложения
  показывает чужую таблицу схематично);
* для любой сущности обязательны первичный ключ и все внешние ключи, если она
  не является заглушкой.

Запуск::

    python tools/verify_diagrams.py
    python tools/verify_diagrams.py --verbose
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DIAGRAMS_DIR = BASE_DIR / "docs" / "diagrams"

ENTITY_RE = re.compile(
    r'^\s*(?P<entity>[A-Za-z_][A-Za-z0-9_]*)\s*'
    r'(?:\["(?P<alias>[^"]*)"\])?\s*'
    r"(?:\:\:\:(?P<classes>[A-Za-z_][A-Za-z0-9_,]*))?\s*\{\s*$"
)
ENTITY_BARE_RE = re.compile(
    r"^\s*(?P<entity>[A-Za-z_][A-Za-z0-9_]*)"
    r'(?:\["(?P<alias>[^"]*)"\])?'
    r"(?:\:\:\:(?P<classes>[A-Za-z_][A-Za-z0-9_,]*))?\s*$"
)
RELATION_RE = re.compile(
    r"^\s*(?P<left>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\:\:\:[A-Za-z_][A-Za-z0-9_,]*)?\s*"
    r"(?P<card>[|}{o]+(?:--|\.\.)[|}{o]+)\s*"
    r"(?P<right>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\:\:\:[A-Za-z_][A-Za-z0-9_,]*)?\s*"
    r'(?::\s*"?(?P<label>[^"]*)"?)?\s*$'
)
ATTRIBUTE_RE = re.compile(
    r"^\s*(?P<type>[A-Za-z][A-Za-z0-9_()\[\]]*)"
    r"\s+(?P<name>\*?[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<rest>.*)$"
)

#: Заглушки внешних приложений (в них проверяются только объявленные колонки).
STUB_CLASS = "external"

#: Таблицы, создаваемые инфраструктурой и не имеющие Django-модели.
UNMODELED_TABLES: dict[str, dict[str, tuple[str, bool, bool]]] = {
    "django_migrations": {
        "id": ("bigint", False, True),
        "app": ("varchar(255)", False, False),
        "name": ("varchar(255)", False, False),
        "applied": ("timestamptz", False, False),
    },
}


class DiagramError(Exception):
    """Нарушение соответствия диаграммы моделям."""


def setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DJANGO_DB_ENGINE", "sqlite")
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    import django

    django.setup()


def column_type(field) -> str:
    """Ожидаемый тип колонки для поля модели."""
    from django.db import models

    if field.is_relation:
        return column_type(field.related_model._meta.pk)
    if isinstance(field, (models.BigAutoField, models.BigIntegerField)):
        return "bigint"
    if isinstance(field, models.PositiveBigIntegerField):
        return "bigint"
    if isinstance(
        field, (models.SmallIntegerField, models.PositiveSmallIntegerField)
    ):
        return "smallint"
    if isinstance(field, models.IntegerField):
        return "integer"
    if isinstance(field, models.BooleanField):
        return "boolean"
    if isinstance(field, models.DateTimeField):
        return "timestamptz"
    if isinstance(field, models.DateField):
        return "date"
    if isinstance(field, models.JSONField):
        return "jsonb"
    if isinstance(field, models.TextField):
        return "text"
    if isinstance(
        field,
        (
            models.CharField,
            models.EmailField,
            models.SlugField,
            models.URLField,
            models.FileField,
            models.ImageField,
        ),
    ):
        return f"varchar({field.max_length})"
    raise DiagramError(f"Неизвестный тип поля {field!r}")


def schema_by_table() -> dict:
    """Фактическая схема: таблица → поля, связи и M2M модели."""
    from django.apps import apps

    allowed_apps = {
        "accounts",
        "catalog",
        "content",
        "moderation",
        "notifications",
        "auth",
        "admin",
        "sessions",
        "contenttypes",
    }
    result: dict[str, dict] = {}
    for app_config in apps.get_app_configs():
        if app_config.label not in allowed_apps:
            continue
        for model in app_config.get_models(include_auto_created=True):
            fields = {}
            for field in model._meta.concrete_fields:
                fields[field.column] = {
                    "name": field.name,
                    "type": column_type(field),
                    "null": bool(field.null),
                    "pk": bool(field.primary_key),
                    "fk": field.related_model._meta.db_table
                    if field.is_relation and field.related_model is not None
                    else None,
                    "unique": bool(field.unique),
                }
            result[model._meta.db_table] = {
                "model": model,
                "fields": fields,
                "m2m": {field.name for field in model._meta.many_to_many},
            }
    return result


def parse_class(raw: str | None) -> str:
    """Возвращает первый CSS-класс сущности."""
    if not raw:
        return ""
    return raw.split(",")[0].strip()


def parse_diagram(path: Path) -> dict:
    """Разбирает .mmd: сущности, атрибуты и связи."""
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    complete = "%% verify: complete" in text

    entities: dict[str, dict] = {}
    relationships: list[dict] = []
    current: dict | None = None

    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("%%"):
            continue

        stripped = line.strip()
        if stripped.startswith("erDiagram") or stripped.startswith("direction "):
            continue
        if stripped.startswith("classDef ") or stripped.startswith("class "):
            continue

        if current is not None:
            if stripped == "}":
                current = None
                continue
            attribute = ATTRIBUTE_RE.match(line)
            if not attribute:
                raise DiagramError(
                    f"{path.name}:{number}: не разобрано поле: {stripped!r}"
                )
            rest = attribute.group("rest").strip()
            comment = ""
            if '"' in rest:
                before, _, after = rest.partition('"')
                comment = after.rsplit('"', 1)[0] if '"' in after else after
                rest = before.strip()
            keys = [key.strip().upper() for key in rest.split(",") if key.strip()]
            field_type = attribute.group("type")
            name = attribute.group("name").lstrip("*")
            current["fields"][name] = {
                "type": field_type,
                "pk": "PK" in keys,
                "fk": "FK" in keys,
                "uk": "UK" in keys,
                "m2m": field_type.lower() == "m2m",
                "comment": comment,
                "nullable_mark": comment.split(":")[0].strip().lower() == "null",
                "line": number,
            }
            continue

        entity = ENTITY_RE.match(line)
        if entity:
            name = entity.group("entity")
            alias = entity.group("alias") or ""
            if name in entities:
                raise DiagramError(
                    f"{path.name}:{number}: сущность {name} объявлена дважды"
                )
            current = {
                "entity": name,
                "alias": alias,
                "table": alias.split("·")[0].strip() if alias else "",
                "cls": parse_class(entity.group("classes")),
                "fields": {},
                "line": number,
            }
            entities[name] = current
            continue

        relation = RELATION_RE.match(line)
        if relation:
            relationships.append(
                {
                    "left": relation.group("left"),
                    "right": relation.group("right"),
                    "card": relation.group("card"),
                    "label": (relation.group("label") or "").strip(),
                    "line": number,
                }
            )
            continue

        bare = ENTITY_BARE_RE.match(line)
        if bare:
            name = bare.group("entity")
            if name not in entities:
                entities[name] = {
                    "entity": name,
                    "alias": bare.group("alias") or "",
                    "table": "",
                    "cls": parse_class(bare.group("classes")),
                    "fields": {},
                    "line": number,
                }
            continue

        raise DiagramError(f"{path.name}:{number}: не разобрана строка: {stripped!r}")

    if current is not None:
        raise DiagramError(f"{path.name}: не закрыт блок сущности {current['entity']}")

    return {
        "path": path,
        "complete": complete,
        "entities": entities,
        "relationships": relationships,
    }


def _verify_unmodeled(entity: dict, name: str) -> list[str]:
    """Проверка таблицы, у которой нет Django-модели."""
    errors: list[str] = []
    label = f"{name}:{entity['line']}"
    expected = UNMODELED_TABLES[entity["table"]]
    for column, attribute in entity["fields"].items():
        if attribute["m2m"]:
            errors.append(f"{label}: у таблицы без модели не может быть M2M")
            continue
        spec = expected.get(column)
        if spec is None:
            errors.append(
                f"{label}: колонка {entity['table']}.{column} не описана в эталоне"
            )
            continue
        column_type_name, is_nullable, is_pk = spec
        if attribute["type"] != column_type_name:
            errors.append(
                f"{label}: {column} объявлена как {attribute['type']}, "
                f"ожидается {column_type_name}"
            )
        if attribute["nullable_mark"] != is_nullable:
            errors.append(f"{label}: {column} — неверная пометка nullable")
        if attribute["pk"] != is_pk:
            errors.append(f"{label}: {column} — неверная пометка PK")
    for column in expected:
        if column not in entity["fields"]:
            errors.append(f"{label}: отсутствует колонка {entity['table']}.{column}")
    return errors


def verify_file(diagram: dict, schema: dict, verbose: bool) -> list[str]:
    """Проверяет одну диаграмму; возвращает список ошибок."""
    name = diagram["path"].name
    errors: list[str] = []
    entities = diagram["entities"]

    pairs = {
        frozenset((relation["left"], relation["right"]))
        for relation in diagram["relationships"]
    }

    for entity in entities.values():
        label = f"{name}:{entity['line']}"
        table = entity["table"]
        if not table:
            errors.append(f"{label}: у сущности {entity['entity']} нет имени таблицы")
            continue

        if table in UNMODELED_TABLES:
            errors.extend(_verify_unmodeled(entity, name))
            continue

        model_info = schema.get(table)
        if model_info is None:
            errors.append(f"{label}: таблица {table} отсутствует в моделях проекта")
            continue

        is_stub = entity["cls"] == STUB_CLASS
        fields = model_info["fields"]

        for column, attribute in entity["fields"].items():
            if attribute["m2m"]:
                if column not in model_info["m2m"]:
                    errors.append(
                        f"{label}: {table}.{column} объявлена как M2M, "
                        "но такой связи в модели нет"
                    )
                continue
            field = fields.get(column)
            if field is None:
                errors.append(f"{label}: колонка {column} отсутствует в {table}")
                continue
            if attribute["type"] != field["type"]:
                errors.append(
                    f"{label}: {table}.{column} объявлена как {attribute['type']}, "
                    f"в модели {field['type']}"
                )
            if attribute["pk"] != field["pk"]:
                errors.append(
                    f"{label}: {table}.{column} помечена PK={attribute['pk']}, "
                    f"в модели PK={field['pk']}"
                )
            if attribute["fk"] != bool(field["fk"]):
                errors.append(
                    f"{label}: {table}.{column} помечена FK={attribute['fk']}, "
                    f"в модели FK={bool(field['fk'])}"
                )
            if attribute["uk"] and not field["unique"]:
                errors.append(
                    f"{label}: {table}.{column} помечена UK, но сама колонка "
                    "не уникальна"
                )
            if attribute["nullable_mark"] != field["null"]:
                errors.append(
                    f"{label}: {table}.{column} помечена nullable="
                    f"{attribute['nullable_mark']}, в модели null={field['null']}"
                )

        if is_stub:
            continue

        # Ключевые колонки обязательны, а в полной диаграмме — все колонки.
        for column, field in fields.items():
            if column in entity["fields"]:
                continue
            if field["pk"] or field["fk"]:
                errors.append(
                    f"{label}: отсутствует ключевая колонка {table}.{column}"
                )
            elif diagram["complete"]:
                errors.append(f"{label}: в полной диаграмме нет колонки {table}.{column}")

        # Внешние ключи должны быть отражены линией связи.
        for column, field in fields.items():
            if not field["fk"]:
                continue
            target_table = field["fk"]
            target_entity = next(
                (
                    candidate["entity"]
                    for candidate in entities.values()
                    if candidate["table"] == target_table
                ),
                None,
            )
            if target_entity is None:
                if verbose:
                    print(
                        f"  · {name}: пропущена внешняя сущность {target_table} "
                        f"(поле {table}.{column})"
                    )
                continue
            if frozenset((entity["entity"], target_entity)) not in pairs:
                errors.append(
                    f"{label}: нет линии связи {entity['entity']} — {target_entity} "
                    f"для внешнего ключа {table}.{column}"
                )

    # Обратная проверка: линия связи должна опираться на реальный FK.
    for relation in diagram["relationships"]:
        left = entities.get(relation["left"])
        right = entities.get(relation["right"])
        if left is None or right is None:
            errors.append(
                f"{name}:{relation['line']}: связь ссылается на необъявленную "
                f"сущность ({relation['left']} — {relation['right']})"
            )
            continue
        pair_tables = {left["table"], right["table"]}
        if not all(pair_tables):
            continue
        linked = False
        for table in pair_tables:
            model_info = schema.get(table)
            if not model_info:
                continue
            if any(
                field["fk"] in pair_tables for field in model_info["fields"].values()
            ):
                linked = True
                break
        if not linked:
            errors.append(
                f"{name}:{relation['line']}: связь {relation['left']} — "
                f"{relation['right']} не подтверждается внешним ключом"
            )

    return errors


def verify_documentation() -> list[str]:
    """Проверяет, что документация ссылается на диаграммы и не разошлась с ними."""
    errors: list[str] = []
    doc_path = BASE_DIR / "docs" / "database-schema.md"
    if not doc_path.exists():
        return [f"не найден файл {doc_path}"]

    text = doc_path.read_text(encoding="utf-8")
    overview = DIAGRAMS_DIR / "database-overview.mmd"
    if overview.exists():
        embedded = overview.read_text(encoding="utf-8-sig").strip()
        if embedded not in text:
            errors.append(
                "docs/database-schema.md: встроенная общая ER-диаграмма "
                "разошлась с docs/diagrams/database-overview.mmd"
            )

    for path in sorted(DIAGRAMS_DIR.glob("*.mmd")):
        if path.name not in text:
            errors.append(
                f"docs/database-schema.md: нет ссылки на диаграмму {path.name}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="показывать пропуски")
    args = parser.parse_args()

    setup_django()
    schema = schema_by_table()

    files = sorted(DIAGRAMS_DIR.glob("*.mmd"))
    if not files:
        print(f"Не найдено ни одного файла в {DIAGRAMS_DIR}")
        return 1

    all_errors: list[str] = []
    for path in files:
        diagram = parse_diagram(path)
        errors = verify_file(diagram, schema, args.verbose)
        status = "OK" if not errors else f"ошибок: {len(errors)}"
        mode = "полная" if diagram["complete"] else "частичная"
        print(
            f"{path.name:26} сущностей: {len(diagram['entities']):2} "
            f"связей: {len(diagram['relationships']):2} ({mode:9}) — {status}"
        )
        all_errors.extend(errors)

    documentation_errors = verify_documentation()
    print(
        "docs/database-schema.md"
        + (
            " — OK"
            if not documentation_errors
            else f" — ошибок: {len(documentation_errors)}"
        )
    )
    all_errors.extend(documentation_errors)

    if all_errors:
        print("\nПроблемы:")
        for error in all_errors:
            print(f"  [x] {error}")
        return 1

    print("\nВсе диаграммы соответствуют моделям, документация актуальна.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
