#!/usr/bin/env bash
# One-command start for a machine that already has Docker Engine and Compose v2.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Нужен Docker Engine. На Ubuntu:"
  echo "  sudo apt-get update"
  echo "  sudo apt-get install -y docker.io docker-compose-v2"
  echo "  sudo usermod -aG docker \"\$USER\""
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Нужен Docker Compose v2 (команда «docker compose»)."
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Создан .env из .env.example"
fi

echo "Собираю и запускаю Postgres, MinIO, бакеты, миграции и API..."
docker compose up --build -d

echo "Жду готовности API..."
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
    echo
    echo "Готово."
    echo "  Веб-интерфейс:  http://127.0.0.1:8000/"
    echo "  Swagger UI:     http://127.0.0.1:8000/docs"
    echo "  MinIO Console:  http://127.0.0.1:9001"
    echo
    echo "Демо-аккаунты (если база была пустой):"
    echo "  admin@example.com      Admin123!"
    echo "  moderator@example.com  Moderator123!"
    echo "  user1@example.com      User1123!"
    echo "  user2@example.com      User2123!"
    exit 0
  fi
  sleep 2
done

echo "API не ответил на /health. Смотрите логи: docker compose logs backend"
exit 1
