# YouTube Clone

Учебный видеохостинг: регистрация и роли, загрузка роликов, лента, поиск, комментарии, реакции, подписки, плейлисты, история просмотра, приватные видео и модерация.

Браузер и Swagger работают на одном процессе FastAPI. Метаданные хранит PostgreSQL 16. Файлы видео и обложки хранит MinIO. Перемотка использует HTTP Range и ответ `206 Partial Content`.

## Стек

- Python 3.11, FastAPI, Pydantic v2
- SQLAlchemy 2.0 (async) и asyncpg
- Alembic
- PostgreSQL 16
- MinIO
- Docker Compose
- Статический веб-интерфейс в `frontend/`

Подробности: [docs/architecture.md](docs/architecture.md) и [docs/database.md](docs/database.md).

## Быстрый старт на Ubuntu

Нужны Docker Engine и плагин Compose v2 (`docker compose`). На чистой системе:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 curl
sudo usermod -aG docker "$USER"
```

После входа в группу `docker` из корня репозитория достаточно одной команды:

```bash
bash run.sh
```

Тот же запуск называется `bash deploy.sh`. Скрипт создаёт `.env` из `.env.example`, если его ещё нет, и выполняет:

```bash
docker compose up --build -d
```

Эта команда сама, без ручных шагов:

1. поднимает PostgreSQL 16 и MinIO;
2. создаёт бакеты `videos` и `thumbnails` (сервис `createbuckets`);
3. применяет миграции `alembic upgrade head`;
4. если таблица `users` пустая, загружает демо-данные (`scripts/seed_data.py`);
5. запускает API и веб-интерфейс на порту 8000.

Повторный `bash run.sh` не затирает уже заполненную базу. Чтобы заново накатить демо на пустую базу, удалите том Postgres: `docker compose down -v`, затем снова `bash run.sh`.

Отключить сид можно переменной `SEED_ON_EMPTY=false` в `.env`.

## Куда заходить

| Что | Адрес |
| --- | --- |
| Веб-интерфейс | http://127.0.0.1:8000/ |
| Swagger UI | http://127.0.0.1:8000/docs |
| Проверка живости | http://127.0.0.1:8000/health |
| Консоль MinIO | http://127.0.0.1:9001 |

Логин MinIO по умолчанию: `minioadmin` / `minioadmin`. Бакеты: `videos`, `thumbnails`.

## Тестовые учётные записи

Пароли задаёт сид при пустой базе. Логин принимает и email, и username.

| Роль | Username | Email | Пароль |
| --- | --- | --- | --- |
| admin | admin | admin@example.com | Admin123! |
| moderator | moderator | moderator@example.com | Moderator123! |
| user | user1 | user1@example.com | User1123! |
| user | user2 | user2@example.com | User2123! |
| user | user3 | user3@example.com | User3123! |

Что уже лежит в демо:

- шесть коротких роликов и обложки в MinIO (один общий тестовый ролик `backend/scripts/assets/sample.mp4`);
- приватные «Internal Release Notes: Q4» видны автору `user1` и `user2` из белого списка;
- `user3` оставил жалобу на «Unbox of the Prototype Console», она в статусе `pending`;
- `user1`, `user2` и `user3` подписаны друг на друга, поэтому у них непустая лента подписок;
- у `user1` публичный плейлист, у `user2` приватный.

Модератор и администратор видят очередь на http://127.0.0.1:8000/#/moderation .

## Автотесты

Тесты лежат в `backend/tests`. Часть проверяет чистые функции (Range, типы файлов, реакции). Сценарии API пишут во временные строки реального Postgres и удаляют своих пользователей.

Когда стек запущен, из корня репозитория:

```bash
docker compose exec backend pytest -q
```

На хосте, при установленных зависимостях и опубликованном порте Postgres:

```bash
cd backend
python -m pip install -r requirements.txt
POSTGRES_HOST=localhost MINIO_ENDPOINT=localhost:9000 python -m pytest -q
```

`pytest.ini` добавляет каталог `backend` в `pythonpath`.

## Полезные команды

```bash
docker compose logs -f backend
docker compose exec backend python -m scripts.seed_data
docker compose down
docker compose down -v
```

Повторный ручной сид идемпотентен: пользователи ищутся по email, ролики и плейлисты по названию. Он восстанавливает демо-поля этих роликов и пароли демо-аккаунтов.

## Структура

```text
backend/app/api        маршруты FastAPI
backend/app/services   правила доступа и сценарии
backend/app/models     таблицы
backend/app/schemas    схемы Pydantic v2
backend/alembic        миграции
backend/tests          pytest
backend/scripts        сид демо-данных
frontend               веб-интерфейс
docs                   архитектура и схема БД
```
