"""Команда первоначальной инициализации ролей USER / MODERATOR / ADMIN.

Использование::

    python manage.py init_roles
    python manage.py init_roles --dry-run
    python manage.py init_roles --no-prune

Команда идемпотентна: повторный запуск не создаёт дублей групп и приводит
набор разрешений к эталонному (см. ``apps.accounts.roles``). Пользователи
в группы автоматически не добавляются.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.roles import ROLE_NAMES, RoleSyncError, sync_roles


class Command(BaseCommand):
    help = "Создаёт группы USER, MODERATOR, ADMIN и назначает им разрешения."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать планируемые изменения, ничего не записывая в БД.",
        )
        parser.add_argument(
            "--no-prune",
            action="store_true",
            help="Только добавлять недостающие разрешения, не удаляя лишние.",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        prune: bool = not options["no_prune"]

        try:
            changes = sync_roles(dry_run=dry_run, prune=prune)
        except RoleSyncError as exc:
            raise CommandError(str(exc)) from exc

        prefix = "[dry-run] " if dry_run else ""
        for role_name in ROLE_NAMES:
            summary = "; ".join(changes[role_name])
            self.stdout.write(f"{prefix}{role_name}: {summary}")

        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Роли синхронизированы: {', '.join(ROLE_NAMES)}."
            )
        )
        if dry_run:
            self.stdout.write("Изменения не сохранены (--dry-run).")
