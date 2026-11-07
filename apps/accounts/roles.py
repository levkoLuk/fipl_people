"""Ролевая модель проекта на штатных группах и разрешениях Django.

Отдельная таблица ролей не создаётся: роли — это записи
:class:`django.contrib.auth.models.Group` с набором разрешений Django.

Соответствие требованиям ТЗ (таблица 1):

``USER``       — права гостя (просмотр) + создание и редактирование
                 собственных материалов, комментирование, профиль,
                 обращения в администрацию;
``MODERATOR``  — права пользователя + проверка, публикация и отклонение
                 материалов и комментариев, обработка жалоб и обращений;
``ADMIN``      — права модератора + управление каталогом, учётными записями
                 и ролями.

Разрешения Django действуют на уровне модели. Проверка «свой объект»
(автор материала, автор комментария, владелец профиля) выполняется в
представлениях и сервисах, поскольку группы не поддерживают объектный
уровень доступа.

Членство в группе ``ADMIN`` не равнозначно ``is_superuser``: суперпользователь
Django получает все права автоматически, а группа ADMIN — фиксированный
набор разрешений, который можно аудировать.
"""

from django.contrib.auth.models import Group, Permission
from django.db.models import Q

ROLE_USER = "USER"
ROLE_MODERATOR = "MODERATOR"
ROLE_ADMIN = "ADMIN"

ROLE_NAMES = (ROLE_USER, ROLE_MODERATOR, ROLE_ADMIN)

# Набор операций CRUD, генерируемый Django для каждой модели.
CRUD = ("add", "change", "delete", "view")

#: Права роли USER.
USER_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "accounts": (
        "view_profile",
        "change_profile",
        "view_profilelink",
        "add_profilelink",
        "change_profilelink",
        "delete_profilelink",
    ),
    "catalog": (
        "view_semester",
        "view_discipline",
        "view_semesterdiscipline",
        "view_materialtype",
    ),
    "content": (
        "view_article",
        "add_article",
        "change_article",
        "view_articleversion",
        "add_articleversion",
        "change_articleversion",
        "view_fileattachment",
        "add_fileattachment",
        "delete_fileattachment",
        "view_comment",
        "add_comment",
        "change_comment",
    ),
    "moderation": (
        "view_report",
        "add_report",
        "view_feedbackmessage",
        "add_feedbackmessage",
    ),
    "notifications": (
        "view_notification",
        "change_notification",
    ),
}

#: Дополнительные права роли MODERATOR (права USER наследуются).
MODERATOR_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "content": (
        "change_articleversion",
        "change_comment",
    ),
    "moderation": (
        "view_moderationevent",
        "view_report",
        "change_report",
        "view_feedbackmessage",
        "change_feedbackmessage",
    ),
    "notifications": (
        "view_notification",
    ),
}

#: Дополнительные права роли ADMIN (права MODERATOR наследуются).
ADMIN_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "accounts": (
        "view_user",
        "add_user",
        "change_user",
        "view_externalaccount",
        "view_profile",
        "change_profile",
    ),
    # Группы и разрешения принадлежат приложению django.contrib.auth.
    #
    # Сознательно НЕ выдаются права add_group / change_group / delete_group:
    # изменение состава разрешений группы эквивалентно повышению привилегий
    # (достаточно выдать группе ADMIN все разрешения). Управление группами
    # оставлено только настоящему суперпользователю Django, а назначение
    # штатных ролей пользователям выполняется через change_user.
    "auth": (
        "view_group",
        "view_permission",
    ),
    "catalog": (
        "add_semester",
        "change_semester",
        "delete_semester",
        "view_semester",
        "add_discipline",
        "change_discipline",
        "delete_discipline",
        "view_discipline",
        "add_semesterdiscipline",
        "change_semesterdiscipline",
        "delete_semesterdiscipline",
        "view_semesterdiscipline",
        "add_materialtype",
        "change_materialtype",
        "delete_materialtype",
        "view_materialtype",
    ),
    "content": (
        "delete_article",
        "change_article",
        "view_article",
        "delete_articleversion",
        "view_articleversion",
        "change_fileattachment",
        "delete_fileattachment",
        "delete_comment",
    ),
    "moderation": (
        "view_moderationevent",
        "delete_report",
        "view_report",
        "delete_feedbackmessage",
        "view_feedbackmessage",
    ),
    "notifications": (
        "view_notification",
        "view_auditlog",
    ),
}


def merge_permissions(
    *mappings: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """Объединяет наборы разрешений нескольких ролей."""
    merged: dict[str, set[str]] = {}
    for mapping in mappings:
        for app_label, codenames in mapping.items():
            merged.setdefault(app_label, set()).update(codenames)
    return {app: tuple(sorted(codenames)) for app, codenames in merged.items()}


#: Итоговый набор разрешений для каждой роли с учётом наследования.
ROLE_PERMISSIONS: dict[str, dict[str, tuple[str, ...]]] = {
    ROLE_USER: merge_permissions(USER_PERMISSIONS),
    ROLE_MODERATOR: merge_permissions(USER_PERMISSIONS, MODERATOR_PERMISSIONS),
    ROLE_ADMIN: merge_permissions(
        USER_PERMISSIONS, MODERATOR_PERMISSIONS, ADMIN_PERMISSIONS
    ),
}


class RoleSyncError(Exception):
    """Ошибка синхронизации ролей (например, разрешения ещё не созданы)."""


def _permission_query(mapping: dict[str, tuple[str, ...]]) -> Q:
    query = Q(pk__in=[])
    for app_label, codenames in mapping.items():
        query |= Q(content_type__app_label=app_label, codename__in=list(codenames))
    return query


def resolve_permissions(mapping: dict[str, tuple[str, ...]]) -> list[Permission]:
    """Возвращает объекты Permission для карты «приложение → кодовые имена»."""
    if not mapping:
        return []
    return list(
        Permission.objects.filter(_permission_query(mapping)).select_related(
            "content_type"
        )
    )


def missing_permissions(mapping: dict[str, tuple[str, ...]]) -> list[str]:
    """Возвращает список отсутствующих разрешений в формате ``app.codename``."""
    found = {
        (permission.content_type.app_label, permission.codename)
        for permission in resolve_permissions(mapping)
    }
    missing = []
    for app_label, codenames in mapping.items():
        for codename in codenames:
            if (app_label, codename) not in found:
                missing.append(f"{app_label}.{codename}")
    return sorted(missing)


def sync_roles(*, dry_run: bool = False, prune: bool = True) -> dict[str, list[str]]:
    """Идемпотентно создаёт группы ролей и назначает им разрешения.

    :param dry_run: только показать, что изменилось бы;
    :param prune: привести набор разрешений группы к эталонному
        (``True``) или только добавить недостающие (``False``);
    :returns: словарь «роль → список изменений».

    Функция не назначает группы пользователям и не создаёт администраторов:
    повышение прав выполняется вручную администратором.
    """
    all_missing = missing_permissions(merge_permissions(*ROLE_PERMISSIONS.values()))
    if all_missing:
        raise RoleSyncError(
            "В базе отсутствуют разрешения: "
            + ", ".join(all_missing)
            + ". Выполните: python manage.py migrate"
        )

    changes: dict[str, list[str]] = {}
    for role_name in ROLE_NAMES:
        mapping = ROLE_PERMISSIONS[role_name]
        desired = set(resolve_permissions(mapping))
        group = Group.objects.filter(name=role_name).first()
        created_group = group is None
        current = set(group.permissions.all()) if group else set()

        added = sorted(
            f"{p.content_type.app_label}.{p.codename}" for p in desired - current
        )
        removed = sorted(
            f"{p.content_type.app_label}.{p.codename}" for p in current - desired
        )

        role_changes: list[str] = []
        if created_group:
            role_changes.append("группа создана")
        if added:
            role_changes.append(f"добавлено разрешений: {len(added)}")
        if removed and prune:
            role_changes.append(f"удалено разрешений: {len(removed)}")
        if not role_changes:
            role_changes.append("без изменений")
        changes[role_name] = role_changes

        if dry_run:
            continue

        if created_group:
            group = Group.objects.create(name=role_name)
        if prune:
            group.permissions.set(desired)
        elif added:
            group.permissions.add(*(desired - current))

    return changes
