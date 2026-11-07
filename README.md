# FIPLPEOPLE.RU — серверная часть

Сайт базы знаний и студенческого сообщества направления «Фундаментальная и
прикладная лингвистика» НГУ. Реализованы структура базы данных, ролевая модель,
модерация публикаций и административная панель. Клиентская часть, REST API и
пользовательские сценарии — следующие этапы.

| Компонент | Версия |
|---|---|
| Python | 3.12 |
| Django | 5.2 LTS |
| PostgreSQL | 16 (целевая СУБД) |
| psycopg | 3 |
| Pillow | 12 |

## Документация

* [Схема базы данных](docs/database-schema.md) — таблицы, поля, связи,
  ограничения, индексы, версионирование, модерация, роли.
* [Общая ER-диаграмма](docs/diagrams/database-overview.mmd) — 17 прикладных
  моделей.
* Отдельные диаграммы: [accounts](docs/diagrams/accounts.mmd),
  [catalog](docs/diagrams/catalog.mmd), [content](docs/diagrams/content.mmd),
  [moderation](docs/diagrams/moderation.mmd),
  [notifications](docs/diagrams/notifications.mmd),
  [служебная схема Django](docs/diagrams/system.mmd).

Диаграммы оформлены в Mermaid ER и открываются в GitHub, VS Code, Obsidian и
[Mermaid Live Editor](https://mermaid.live). SVG-версии не созданы: рендерер
Mermaid CLI требует запуска headless-браузера, что недоступно в текущем
окружении (`spawn EPERM`). Файлы `.mmd` являются источником истины и
проверяются скриптом (см. «Проверка диаграмм»).

## Структура проекта

```
manage.py
config/                 настройки, загрузчик .env, URL, WSGI/ASGI
apps/
  accounts/             User, ExternalAccount, Profile, ProfileLink, роли
  catalog/              Semester, Discipline, SemesterDiscipline, MaterialType
  content/              Article, ArticleVersion, FileAttachment, Comment, services
  moderation/           ModerationEvent, Report, FeedbackMessage, services
  notifications/        Notification, AuditLog
docs/
  database-schema.md    описание схемы БД
  diagrams/*.mmd        ER-диаграммы (Mermaid)
tools/
  verify_diagrams.py    сверка диаграмм с моделями
requirements.txt        зависимости
.env.example            пример переменных окружения
```

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux/macOS

pip install -r requirements.txt
```

### Переменные окружения

Настройки читаются из переменных окружения. Дополнительно поддерживается файл
**`.env`** в корне проекта: его загружает модуль `config/env.py` до чтения
настроек. Значения из настоящего окружения имеют приоритет, поэтому `.env`
удобен для локальной разработки, а на сервере переменные можно задавать
штатными средствами (systemd, docker compose).

```bash
cp .env.example .env    # Windows: copy .env.example .env
```

Минимальный набор:

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `DJANGO_SECRET_KEY` | секретный ключ | обязателен при `DEBUG=false` |
| `DJANGO_DEBUG` | режим отладки | `true` |
| `DJANGO_ALLOWED_HOSTS` | список хостов через запятую | `localhost,127.0.0.1` |
| `DJANGO_DB_ENGINE` | `postgresql` или `sqlite` | `postgresql` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | подключение к PostgreSQL | `fiplpeople`, `fiplpeople`, пусто, `127.0.0.1`, `5432` |
| `POSTGRES_SSLMODE` | режим SSL | `prefer` |
| `MAX_ATTACHMENT_SIZE_BYTES` | предел размера файла | 209715200 |
| `ALLOWED_EMAIL_DOMAIN` | домен Google-аккаунтов | `g.nsu.ru` |
| `DJANGO_ENV_FILE` | путь к файлу `.env` | `<проект>/.env` |

Путь к загруженному файлу доступен в настройках как `LOADED_ENV_FILE`
(`None`, если файла нет).

## Первоначальная настройка

```bash
# 1. Проверки
python manage.py check
python manage.py makemigrations --check --dry-run   # ожидается "No changes detected"

# 2. Схема базы данных
python manage.py migrate

# 3. Роли USER / MODERATOR / ADMIN (идемпотентно)
python manage.py init_roles
python manage.py init_roles --dry-run     # предварительный просмотр

# 4. Служебная учётная запись для /admin/ (пароль нужен только персоналу)
python manage.py createsuperuser

# 5. Запуск
python manage.py runserver
```

Роли на пользователей назначаются вручную в административной панели
(`/admin/` → «Пользователи» → поле «Роли»). `init_roles` никогда не повышает
права автоматически.

## Команды

```bash
python manage.py check                        # проверка конфигурации
python manage.py makemigrations --check --dry-run
python manage.py migrate                      # применить миграции
python manage.py init_roles                   # синхронизировать роли и права
python manage.py createsuperuser              # администратор для входа в панель
python manage.py test                         # автотесты (PostgreSQL)
DJANGO_DB_ENGINE=sqlite python manage.py test # автотесты на SQLite
python tools/verify_diagrams.py               # сверить ER-диаграммы с моделями
```

## Тесты

235 тестов проверяют:

* связи и ограничения целостности, включая частичные уникальные индексы
  «одна опубликованная» и «одна ожидающая проверки редакция на статью»;
* сценарий версионирования статьи и конкурентную публикацию (блокировка
  родительской статьи, повторное чтение под блокировкой, атомарность);
* разграничение полномочий в административной панели (запрет выдачи
  `is_superuser`, запрет управления группами и чужих паролей);
* отсутствие повторных уведомлений по жалобам и обращениям;
* создание комментариев и ответов только в рамках одной статьи;
* ограничение размера файла и жизненный цикл файлов вложений;
* нормализацию email и загрузку `.env`;
* «только просмотр» для журналов модерации и аудита.

## Административная панель

`/admin/` — управление каталогом, материалами, комментариями, жалобами,
обращениями и ролями.

* статьи удаляются мягко (действия «Пометить как удалённые» / «Восстановить»);
* `ModerationEvent` и `AuditLog` доступны только для просмотра;
* статус редакции и комментария меняется действиями «Опубликовать»,
  «Отклонить», «Вернуть на исправление», «Скрыть»;
* `is_staff`, `is_superuser`, состав групп и чужие пароли может изменять только
  суперпользователь; обычный администратор назначает роли USER / MODERATOR /
  ADMIN, блокирует пользователей и управляет каталогом.

## Безопасность

* доменные пользователи не имеют пароля (`set_unusable_password`), вход
  предполагается через Google OpenID Connect (модель `ExternalAccount` готова);
* `AUTH_USER_MODEL = accounts.User`, email — уникальный идентификатор,
  регистронезависимая уникальность на уровне БД;
* привилегии проверяются на сервере, а не только скрытием полей в интерфейсе;
* рекомендации для production: `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY`,
  HTTPS (`SECURE_SSL_REDIRECT`), резервное копирование PostgreSQL.
