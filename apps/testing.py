"""Вспомогательные функции для тестов.

Модуль используется только автотестами и не является частью прикладной
логики. Функции создают минимальный набор связанных объектов.
"""

from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.accounts.roles import ROLE_ADMIN, ROLE_MODERATOR, ROLE_USER
from apps.catalog.models import Discipline, MaterialType, Semester, SemesterDiscipline
from apps.content.models import Article, ArticleVersion
from apps.content.services import create_draft_version, submit_for_review


def create_user(email: str = "student@g.nsu.ru", *, role: str | None = None, **extra) -> User:
    """Создаёт пользователя; при необходимости добавляет в группу роли."""
    extra.setdefault("is_active", True)
    user = User.objects.create_user(email=email, **extra)
    if role is not None:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)
    return user


def create_student(email: str = "student@g.nsu.ru", **extra) -> User:
    return create_user(email, role=ROLE_USER, **extra)


def create_moderator(email: str = "moderator@g.nsu.ru", **extra) -> User:
    return create_user(email, role=ROLE_MODERATOR, **extra)


def create_admin(email: str = "admin@g.nsu.ru", **extra) -> User:
    return create_user(email, role=ROLE_ADMIN, **extra)


def create_catalog(
    *,
    semester_number: int = 3,
    semester_name: str = "3 семестр",
    discipline_name: str = "Морфология",
) -> tuple[Semester, Discipline, SemesterDiscipline, MaterialType]:
    """Гарантирует наличие семестра, дисциплины и типа материала «Лекции».

    Функция идемпотентна: повторный вызов с теми же аргументами возвращает
    уже созданные объекты, поэтому её можно вызывать из разных тестов.
    """
    semester, _ = Semester.objects.get_or_create(
        number=semester_number, defaults={"name": semester_name}
    )
    discipline = Discipline.objects.filter(name=discipline_name).first()
    if discipline is None:
        discipline = Discipline.objects.create(
            name=discipline_name,
            slug=f"discipline-{Discipline.objects.count() + 1}",
        )
    semester_discipline, _ = SemesterDiscipline.objects.get_or_create(
        semester=semester, discipline=discipline
    )
    material_type, _ = MaterialType.objects.get_or_create(
        slug="lektsii", defaults={"name": "Лекции"}
    )
    return semester, discipline, semester_discipline, material_type


def create_article(
    author: User,
    *,
    catalog: tuple | None = None,
    title: str = "Конспект лекций",
    content: str = "Содержание конспекта.",
) -> tuple[Article, ArticleVersion]:
    """Создаёт статью с первой редакцией в статусе ``draft``."""
    if catalog is None:
        catalog = create_catalog()
    _, _, semester_discipline, material_type = catalog
    article = Article.objects.create(author=author)
    version = create_draft_version(
        article,
        created_by=author,
        semester_discipline=semester_discipline,
        material_type=material_type,
        title=title,
        content=content,
    )
    return article, version


def create_pending_article(
    author: User,
    *,
    catalog: tuple | None = None,
    title: str = "Конспект лекций",
) -> tuple[Article, ArticleVersion]:
    """Создаёт статью с редакцией, отправленной на проверку."""
    article, version = create_article(author, catalog=catalog, title=title)
    return article, submit_for_review(version)


def create_published_article(
    author: User,
    moderator: User,
    *,
    catalog: tuple | None = None,
    title: str = "Конспект лекций",
) -> tuple[Article, ArticleVersion]:
    """Создаёт статью с опубликованной первой редакцией."""
    from apps.content.services import publish_version

    article, version = create_pending_article(author, catalog=catalog, title=title)
    return article, publish_version(version, moderator=moderator)
