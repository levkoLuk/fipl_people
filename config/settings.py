"""Настройки Django-проекта FIPLPEOPLE.RU.

Параметры читаются из переменных окружения. Дополнительно поддерживается файл
``.env`` в корне проекта (см. ``.env.example``): он загружается модулем
:mod:`config.env` до чтения настроек, при этом настоящие переменные окружения
имеют приоритет.

Целевая СУБД — PostgreSQL. Для локальных проверок без сервера PostgreSQL
можно переключиться на SQLite: ``DJANGO_DB_ENGINE=sqlite``.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.env import load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent

#: Путь к загруженному файлу ``.env`` (``None``, если файла нет).
LOADED_ENV_FILE = load_env_file(BASE_DIR)


def env_bool(name: str, default: bool = False) -> bool:
    """Читает логическое значение из переменной среды."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: tuple[str, ...] = ()) -> list[str]:
    """Читает список значений, разделённых запятой."""
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", True)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY обязателен при DJANGO_DEBUG=false."
        )
    SECRET_KEY = "dev-only-insecure-key-change-me"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ("localhost", "127.0.0.1"))
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Приложения проекта FIPLPEOPLE.RU.
    "apps.accounts",
    "apps.catalog",
    "apps.content",
    "apps.moderation",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------
# Целевая СУБД — PostgreSQL. Значение DJANGO_DB_ENGINE=sqlite предназначено
# только для локальных проверок и автотестов на машинах без сервера PostgreSQL.
DB_ENGINE = os.getenv("DJANGO_DB_ENGINE", "postgresql").strip().lower()

if DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.getenv("DJANGO_DB_NAME", str(BASE_DIR / "db.sqlite3")),
            "OPTIONS": {"timeout": 20},
        }
    }
elif DB_ENGINE in {"postgresql", "postgres", "psql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "fiplpeople"),
            "USER": os.getenv("POSTGRES_USER", "fiplpeople"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("POSTGRES_CONN_MAX_AGE", "60")),
            "OPTIONS": {},
            "TEST": {"NAME": os.getenv("POSTGRES_TEST_DB", "test_fiplpeople")},
        }
    }
    if env_bool("POSTGRES_REQUIRE_SSL", True):
        DATABASES["default"]["OPTIONS"]["sslmode"] = os.getenv(
            "POSTGRES_SSLMODE", "prefer"
        )
else:
    raise ImproperlyConfigured(
        f"Неподдерживаемое значение DJANGO_DB_ENGINE={DB_ENGINE!r}. "
        "Допустимо: 'postgresql' или 'sqlite'."
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Аутентификация
# ---------------------------------------------------------------------------
# Пользовательская модель с email в качестве идентификатора.
AUTH_USER_MODEL = "accounts.User"

# Штатные группы и разрешения Django — единственный механизм ролей.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

# Пользователи входят через Google (см. ExternalAccount); пароли для них
# не задаются (set_unusable_password). Валидаторы применяются только к
# служебным учётным записям персонала, создаваемым через createsuperuser.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Интернационализация
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Novosibirsk"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Статические файлы и пользовательские загрузки
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Учебные материалы (PDF, DOCX, ZIP, DJVU) могут быть крупными: файлы
# целиком уходят в файловое хранилище, в БД остаются только метаданные.
FILE_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("FILE_UPLOAD_MAX_MEMORY_SIZE", str(10 * 1024 * 1024))
)
DATA_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", str(25 * 1024 * 1024))
)

# Ограничение размера одного прикреплённого файла (байт).
MAX_ATTACHMENT_SIZE_BYTES = int(
    os.getenv("MAX_ATTACHMENT_SIZE_BYTES", str(200 * 1024 * 1024))
)

# ---------------------------------------------------------------------------
# Почта (уведомления и обращения администрации)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.getenv(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.getenv("DJANGO_DEFAULT_FROM_EMAIL", "noreply@fiplpeople.ru")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Домен, которому должны принадлежать подтверждённые адреса Google-аккаунтов.
ALLOWED_EMAIL_DOMAIN = os.getenv("ALLOWED_EMAIL_DOMAIN", "g.nsu.ru")

# ---------------------------------------------------------------------------
# Безопасность (активируется на production-окружении)
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
