"""Модели приложения accounts.

Состав:
    * :class:`User` — пользовательская модель Django с email как идентификатором;
    * :class:`ExternalAccount` — связь пользователя с внешним провайдером (Google);
    * :class:`Profile` — профиль участника сообщества;
    * :class:`ProfileLink` — ссылки в профиле с индивидуальной видимостью.

Пароли пользователей не хранятся: учётная запись создаётся и подтверждается
через Google, для локального пользователя вызывается
``set_unusable_password()``. Служебные учётные записи персонала могут иметь
пароль (требуется штатной странице входа Django Admin).
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


def normalize_email_address(email: str) -> str:
    """Нормализует адрес электронной почты для хранения и сравнения.

    Доменная политика проекта (``@g.nsu.ru``) не различает регистр, поэтому
    адрес приводится к нижнему регистру целиком. Это защищает от появления
    двух учётных записей ``Ivan@g.nsu.ru`` и ``ivan@g.nsu.ru``.
    """
    return (email or "").strip().lower()


class UserManager(BaseUserManager):
    """Менеджер пользователей, использующий email вместо username."""

    use_in_migrations = True

    def _prepare(self, email: str, password: str | None, extra_fields: dict) -> "User":
        if not email:
            raise ValueError("Адрес электронной почты обязателен.")
        user = self.model(email=normalize_email_address(email), **extra_fields)
        if password:
            user.set_password(password)
        else:
            # Пароль не хранится: вход выполняется через внешний провайдер.
            user.set_unusable_password()
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        """Создаёт обычного пользователя (без прав персонала)."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self._prepare(email, password, extra_fields)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        """Создаёт суперпользователя для служебного доступа в Django Admin."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Суперпользователь должен иметь is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Суперпользователь должен иметь is_superuser=True.")
        if not password:
            raise ValueError("Для суперпользователя требуется пароль.")
        user = self._prepare(email, password, extra_fields)
        user.save(using=self._db)
        return user


class User(AbstractUser):
    """Учётная запись участника сообщества.

    Поле ``username`` не используется: идентификатором служит уникальный email.
    Группы и разрешения берутся из штатных механизмов Django
    (``django.contrib.auth``): роли USER, MODERATOR и ADMIN —
    это записи :class:`django.contrib.auth.models.Group`.
    """

    username = None
    email = models.EmailField(
        "электронная почта",
        unique=True,
        help_text="Подтверждённый адрес в домене g.nsu.ru.",
    )
    is_active = models.BooleanField(
        "активна",
        default=True,
        help_text="Снятие флага блокирует вход без удаления данных.",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        ordering = ("-date_joined",)
        constraints = [
            # Регистронезависимая уникальность email: адреса хранятся в нижнем
            # регистре (normalize_email_address), ограничение защищает от
            # дублей, созданных в обход менеджера.
            models.UniqueConstraint(
                Lower("email"),
                name="uniq_user_email_case_insensitive",
            ),
        ]
        indexes = [
            models.Index(fields=["is_active"], name="user_is_active_idx"),
        ]

    def __str__(self) -> str:
        return self.email

    def clean(self) -> None:
        super().clean()
        self.email = normalize_email_address(self.email)

    def save(self, *args, **kwargs):
        """Сохраняет email в нормализованном виде при любой записи."""
        if self.email:
            self.email = normalize_email_address(self.email)
        return super().save(*args, **kwargs)

    @property
    def role_names(self) -> set[str]:
        """Названия групп пользователя (роли USER/MODERATOR/ADMIN)."""
        return set(self.groups.values_list("name", flat=True))

    def has_role(self, *role_names: str) -> bool:
        """Проверяет членство в указанных группах."""
        if not role_names:
            return False
        return bool(self.role_names.intersection(role_names))

    def block(self) -> None:
        """Блокирует учётную запись, сохраняя связанные данные."""
        self.is_active = False
        self.save(update_fields=["is_active"])

    def unblock(self) -> None:
        """Снимает блокировку учётной записи."""
        self.is_active = True
        self.save(update_fields=["is_active"])


class ExternalAccount(models.Model):
    """Связь локального пользователя с внешним провайдером авторизации.

    OAuth-токены и секреты намеренно не хранятся: после проверки ответа
    провайдера система сохраняет только идентификатор и признак
    подтверждённого email.
    """

    class Provider(models.TextChoices):
        GOOGLE = "google", "Google"

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="external_accounts",
        verbose_name="пользователь",
    )
    provider = models.CharField(
        "провайдер",
        max_length=32,
        choices=Provider.choices,
        default=Provider.GOOGLE,
    )
    provider_uid = models.CharField(
        "идентификатор у провайдера",
        max_length=255,
        help_text="Значение поля sub в ответе Google OpenID Connect.",
    )
    email_verified = models.BooleanField(
        "email подтверждён",
        default=False,
        help_text="Признак email_verified из ответа провайдера.",
    )
    created_at = models.DateTimeField("создана", auto_now_add=True)
    updated_at = models.DateTimeField("изменена", auto_now=True)

    class Meta:
        verbose_name = "внешний аккаунт"
        verbose_name_plural = "внешние аккаунты"
        ordering = ("provider", "user_id")
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_uid"],
                name="uniq_external_account_provider_uid",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "provider"], name="ext_acc_user_provider_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.provider_uid}"


def avatar_upload_path(instance: "Profile", filename: str) -> str:
    """Каталог для аватара: media/avatars/<user_id>/<имя файла>."""
    return f"avatars/{instance.user_id}/{filename}"


class Profile(models.Model):
    """Публичный профиль участника сообщества.

    Один пользователь имеет ровно один профиль: связь ``OneToOneField``
    запрещает дублирование на уровне БД.
    """

    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="пользователь",
    )
    display_name = models.CharField(
        "отображаемое имя",
        max_length=150,
        blank=True,
        help_text="Имя, видимое другим участникам вместо email.",
    )
    bio = models.TextField("о себе", blank=True)
    avatar = models.ImageField(
        "аватар",
        upload_to=avatar_upload_path,
        max_length=255,
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])],
    )
    is_public = models.BooleanField(
        "профиль открыт",
        default=True,
        help_text="Если выключено, профиль не показывается в разделе «Люди».",
    )
    created_at = models.DateTimeField("создан", auto_now_add=True)
    updated_at = models.DateTimeField("обновлён", auto_now=True)

    class Meta:
        verbose_name = "профиль"
        verbose_name_plural = "профили"
        ordering = ("display_name", "user_id")
        indexes = [
            models.Index(fields=["is_public"], name="profile_is_public_idx"),
        ]

    def __str__(self) -> str:
        return self.display_name or self.user.email

    @property
    def public_links(self):
        """Ссылки, разрешённые к показу другим участникам."""
        return self.links.filter(is_public=True)

    def touch(self) -> None:
        """Обновляет отметку изменения профиля."""
        self.updated_at = timezone.now()
        self.save(update_fields=["updated_at"])


class ProfileLink(models.Model):
    """Ссылка в профиле пользователя (сайт, GitHub, Telegram и т. п.)."""

    profile = models.ForeignKey(
        "accounts.Profile",
        on_delete=models.CASCADE,
        related_name="links",
        verbose_name="профиль",
    )
    title = models.CharField("название", max_length=150)
    url = models.URLField("адрес", max_length=500)
    is_public = models.BooleanField(
        "видна другим",
        default=True,
        help_text="Пользователь сам определяет видимость каждой ссылки.",
    )

    class Meta:
        verbose_name = "ссылка профиля"
        verbose_name_plural = "ссылки профиля"
        ordering = ("profile_id", "title")
        indexes = [
            models.Index(fields=["profile", "is_public"], name="profilelink_profile_pub_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title}: {self.url}"
