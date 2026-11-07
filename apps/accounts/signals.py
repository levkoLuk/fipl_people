"""Сигналы приложения accounts."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import Profile, User


@receiver(post_save, sender=User, dispatch_uid="accounts.create_profile_for_user")
def create_profile_for_user(sender, instance: User, created: bool, **kwargs) -> None:
    """Гарантирует наличие профиля у каждого пользователя.

    Операция идемпотентна: повторный вызов не создаёт второй профиль.
    """
    if created:
        Profile.objects.get_or_create(user=instance)
