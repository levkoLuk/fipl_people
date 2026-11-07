"""Конфигурация приложения accounts."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Пользователи, внешние аккаунты, профили и ролевая модель."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Пользователи и профили"

    def ready(self) -> None:
        # Регистрация сигналов создания профиля при появлении пользователя.
        from apps.accounts import signals  # noqa: F401
