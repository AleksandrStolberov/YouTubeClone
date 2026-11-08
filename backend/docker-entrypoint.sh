#!/bin/sh
set -eu

echo "Applying database migrations..."
alembic upgrade head

seed_on_empty="${SEED_ON_EMPTY:-true}"
if [ "$seed_on_empty" = "true" ]; then
  echo "Checking whether demo data is needed..."
  user_count="$(python -c '
import asyncio
from sqlalchemy import func, select
from app.core.database import async_engine, async_sessionmaker
from app.models.user import User

async def main() -> None:
    try:
        async with async_sessionmaker() as session:
            count = await session.scalar(select(func.count()).select_from(User))
        print(int(count or 0))
    finally:
        await async_engine.dispose()

asyncio.run(main())
')"
  if [ "$user_count" = "0" ]; then
    echo "Database is empty. Seeding demo data..."
    python -m scripts.seed_data
  else
    echo "Database already has ${user_count} users. Skipping demo seed."
  fi
else
  echo "SEED_ON_EMPTY is disabled. Skipping demo seed."
fi

exec "$@"
