"""Формы приложения accounts.

Формы административной панели реализуют серверное разграничение полномочий:
обычный администратор (группа ``ADMIN``, но не ``is_superuser``) не видит и не
может изменить служебные флаги, произвольные группы и чужие пароли. Скрытие
полей в интерфейсе дополняется запретами в :mod:`apps.accounts.admin`, поэтому
подмена HTTP-запроса не даёт повысить привилегии.
"""

from django import forms
from django.contrib.auth.forms import BaseUserCreationForm, UserChangeForm
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from apps.accounts.models import User, normalize_email_address
from apps.accounts.roles import ROLE_NAMES

#: Поля пользователя, доступные только настоящему суперпользователю Django.
SUPERUSER_ONLY_FIELDS = ("is_superuser", "is_staff", "groups", "user_permissions")


class EmailUniquenessMixin:
    """Нормализует email и проверяет уникальность без учёта регистра."""

    def clean_email(self) -> str:
        email = normalize_email_address(self.cleaned_data["email"])
        duplicates = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Пользователь с таким адресом уже зарегистрирован.")
        return email


class UserCreationForm(EmailUniquenessMixin, BaseUserCreationForm):
    """Создание пользователя по email (поле username не используется).

    Форма не содержит служебных флагов: новая учётная запись создаётся
    обычным пользователем без прав персонала.
    """

    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)

    class Meta(BaseUserCreationForm.Meta):
        model = User
        fields = ("email",)


class UserUpdateForm(EmailUniquenessMixin, UserChangeForm):
    """Редактирование пользователя с учётом полномочий действующего лица.

    * суперпользователь редактирует всё, включая произвольные группы;
    * обычный администратор может менять данные пользователя, блокировать его
      и назначать штатные роли USER / MODERATOR / ADMIN через поле ``roles``;
    * служебные флаги (``is_superuser``, ``is_staff``), произвольные группы,
      индивидуальные разрешения и чужой пароль обычному администратору
      недоступны.
    """

    roles = forms.ModelMultipleChoiceField(
        label="Роли",
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Штатные роли USER / MODERATOR / ADMIN.",
    )

    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor

        if self._actor_is_superuser:
            # Суперпользователь управляет членством в группах напрямую.
            self.fields.pop("roles", None)
            return

        for field_name in SUPERUSER_ONLY_FIELDS:
            self.fields.pop(field_name, None)

        editing_other_user = bool(self.instance.pk) and (
            self.instance.pk != getattr(self.actor, "pk", None)
        )
        if editing_other_user:
            # Сброс чужого пароля — путь к захвату учётной записи.
            self.fields.pop("password", None)

        self.fields["roles"].queryset = Group.objects.filter(
            name__in=ROLE_NAMES
        ).order_by("name")
        if self.instance.pk:
            self.fields["roles"].initial = self.instance.groups.filter(
                name__in=ROLE_NAMES
            )

    @property
    def _actor_is_superuser(self) -> bool:
        """Полномочия действующего лица; по умолчанию — минимальные."""
        return bool(getattr(self.actor, "is_superuser", False))
