"""Настройка панели администратора для users, профилей и ролей.

Разграничение полномочий (проверяется на сервере, а не только скрытием полей):

* ``is_superuser`` и ``is_staff`` меняет только настоящий суперпользователь
  Django; членство в группе ``ADMIN`` таких прав не даёт;
* разрешения и состав групп (``auth.Group``) редактирует только
  суперпользователь — иначе выдача группе всех разрешений была бы обходом
  ролевой модели;
* обычный администратор назначает штатные роли USER / MODERATOR / ADMIN
  через поле «Роли» и блокирует учётные записи;
* обычный администратор не может изменять и удалять суперпользователей и
  сбрасывать чужие пароли (захват учётной записи);
* привязка внешних аккаунтов Google доступна только суперпользователю:
  иначе администратор мог бы привязать свою учётную запись Google к чужому
  профилю и войти под ним.
"""

from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import SUPERUSER_ONLY_FIELDS, UserCreationForm, UserUpdateForm
from apps.accounts.models import ExternalAccount, Profile, ProfileLink, User
from apps.accounts.roles import ROLE_ADMIN, ROLE_MODERATOR, ROLE_NAMES, ROLE_USER
from apps.notifications.models import AuditLog
from apps.notifications.services import record_audit

# Штатная регистрация групп заменяется расширенной (см. RoleGroupAdmin).
admin.site.unregister(Group)


class ProfileLinkInline(admin.TabularInline):
    """Ссылки профиля редактируются вместе с профилем."""

    model = ProfileLink
    extra = 1
    fields = ("title", "url", "is_public")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "is_public", "links_count", "updated_at")
    list_select_related = ("user",)
    list_filter = ("is_public",)
    search_fields = ("display_name", "user__email", "bio")
    readonly_fields = ("created_at", "updated_at")
    inlines = (ProfileLinkInline,)
    autocomplete_fields = ("user",)

    @admin.display(description="ссылок")
    def links_count(self, obj: Profile) -> int:
        return obj.links.count()


@admin.register(ExternalAccount)
class ExternalAccountAdmin(admin.ModelAdmin):
    """Привязка внешних аккаунтов — только суперпользователь.

    Ручная привязка чужого Google-идентификатора к локальной учётной записи
    равносильна входу под этим пользователем, поэтому операция ограничена.
    """

    list_display = ("provider", "provider_uid", "user", "email_verified", "created_at")
    list_select_related = ("user",)
    list_filter = ("provider", "email_verified")
    search_fields = ("provider_uid", "user__email")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)

    def has_add_permission(self, request) -> bool:
        return bool(request.user.is_superuser)

    def has_change_permission(self, request, obj=None) -> bool:
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None) -> bool:
        return bool(request.user.is_superuser)


@admin.register(ProfileLink)
class ProfileLinkAdmin(admin.ModelAdmin):
    """Отдельный список ссылок: поиск и фильтр видимости."""

    list_display = ("title", "profile", "url", "is_public")
    list_filter = ("is_public",)
    search_fields = ("title", "url", "profile__display_name", "profile__user__email")
    list_select_related = ("profile", "profile__user")
    autocomplete_fields = ("profile",)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Управление учётными записями: блокировка, роли, служебные флаги."""

    form = UserUpdateForm
    add_form = UserCreationForm
    ordering = ("email",)
    list_display = (
        "email",
        "roles_display",
        "is_active",
        "is_staff",
        "is_superuser",
        "date_joined",
        "last_login",
    )
    list_filter = ("is_active", "is_staff", "is_superuser", "groups")
    search_fields = ("email", "profile__display_name")
    readonly_fields = ("last_login", "date_joined")
    filter_horizontal = ("groups", "user_permissions")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Профиль"),
            {"fields": ("first_name", "last_name")},
        ),
        (
            _("Права"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (_("Даты"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )

    # ------------------------------------------------------------------
    # Полномочия
    # ------------------------------------------------------------------

    def get_form(self, request, obj=None, change=False, **kwargs):
        """Передаёт форму действующее лицо, чтобы она убрала недоступные поля."""
        base_form = super().get_form(request, obj, change=change, **kwargs)
        actor = request.user

        class ActorBoundForm(base_form):
            def __init__(self, *args, **inner_kwargs):
                inner_kwargs["actor"] = actor
                super().__init__(*args, **inner_kwargs)

        return ActorBoundForm

    def get_fieldsets(self, request, obj=None):
        """Раскладка формы для обычного администратора.

        Служебные флаги, произвольные группы и индивидуальные разрешения не
        показываются; вместо них используется поле «Роли» со штатными ролями.
        """
        if request.user.is_superuser:
            return super().get_fieldsets(request, obj)

        editing_other_user = obj is not None and obj.pk != request.user.pk
        account_fields = ["email"]
        if not editing_other_user:
            account_fields.append("password")

        return (
            (None, {"fields": account_fields}),
            (_("Профиль"), {"fields": ("first_name", "last_name")}),
            (_("Права"), {"fields": ("is_active", "roles")}),
            (_("Даты"), {"fields": ("last_login", "date_joined")}),
        )

    def has_change_permission(self, request, obj=None) -> bool:
        """Суперпользователя может изменять только суперпользователь."""
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None) -> bool:
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)

    def user_change_password(self, request, id, form_url=""):
        """Сброс чужого пароля разрешён только суперпользователю."""
        target = get_object_or_404(User, pk=id)
        if not request.user.is_superuser and target.pk != request.user.pk:
            raise PermissionDenied(
                "Менять пароль другого пользователя может только суперпользователь."
            )
        return super().user_change_password(request, id, form_url)

    @admin.display(description="роли")
    def roles_display(self, obj: User) -> str:
        return ", ".join(sorted(obj.role_names)) or "—"

    # ------------------------------------------------------------------
    # Сохранение
    # ------------------------------------------------------------------

    def save_model(self, request, obj, form, change) -> None:
        """Страхует служебные флаги и пишет блокировку в журнал действий.

        Роли фиксируются позже — в :meth:`save_related`, потому что связь
        «пользователь — группы» сохраняется после основного объекта.
        """
        previous = None
        if change and obj.pk:
            previous = User.objects.filter(pk=obj.pk).first()

        if not request.user.is_superuser and previous is not None:
            if previous.is_superuser:
                raise PermissionDenied("Изменение суперпользователя запрещено.")
            if (
                previous.is_staff != obj.is_staff
                or previous.is_superuser != obj.is_superuser
            ):
                raise PermissionDenied(
                    "Изменять служебные флаги может только суперпользователь."
                )

        # Снимок состояния для журнала: save_related выполнится позже.
        request._fipl_previous_roles = previous.role_names if previous else set()
        request._fipl_previous_active = previous.is_active if previous else None

        super().save_model(request, obj, form, change)

        if (
            request._fipl_previous_active is not None
            and request._fipl_previous_active != obj.is_active
        ):
            action = (
                AuditLog.Action.USER_BLOCKED
                if not obj.is_active
                else AuditLog.Action.USER_UNBLOCKED
            )
            record_audit(
                actor=request.user,
                action=action,
                obj=obj,
                details={"email": obj.email},
            )

    def save_related(self, request, form, formsets, change) -> None:
        """Применяет роли и фиксирует их изменение в журнале действий."""
        super().save_related(request, form, formsets, change)

        instance = form.instance
        if not request.user.is_superuser:
            if "roles" in getattr(form, "cleaned_data", {}):
                selected = set(form.cleaned_data["roles"])
                # Произвольные (нештатные) группы обычный администратор не меняет.
                preserved = {
                    group
                    for group in instance.groups.all()
                    if group.name not in ROLE_NAMES
                }
                instance.groups.set(selected | preserved)

        if not change:
            return

        previous_roles = getattr(request, "_fipl_previous_roles", set())
        current_roles = instance.role_names
        if previous_roles != current_roles:
            record_audit(
                actor=request.user,
                action=AuditLog.Action.ROLE_CHANGED,
                obj=instance,
                details={
                    "added": sorted(current_roles - previous_roles),
                    "removed": sorted(previous_roles - current_roles),
                    "roles": sorted(current_roles),
                },
            )


@admin.register(Group)
class RoleGroupAdmin(DjangoGroupAdmin):
    """Просмотр ролей USER / MODERATOR / ADMIN и их разрешений.

    Изменение состава групп и их разрешений — прерогатива суперпользователя:
    выдача группе всех разрешений обходила бы ролевую модель.
    """

    list_display = ("name", "permissions_count", "is_system_role")
    search_fields = ("name",)
    filter_horizontal = ("permissions",)

    @admin.display(description="разрешений")
    def permissions_count(self, obj: Group) -> int:
        return obj.permissions.count()

    @admin.display(boolean=True, description="штатная роль")
    def is_system_role(self, obj: Group) -> bool:
        return obj.name in {ROLE_USER, ROLE_MODERATOR, ROLE_ADMIN}

    def has_add_permission(self, request) -> bool:
        return bool(request.user.is_superuser)

    def has_change_permission(self, request, obj=None) -> bool:
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None) -> bool:
        return bool(request.user.is_superuser)
