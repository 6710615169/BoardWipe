#!/usr/bin/env bash
# Render build command: ./build.sh
set -o errexit  # stop at the first error so a broken build never goes live

pip install -r requirements.txt

cd src
python manage.py collectstatic --noinput
python manage.py migrate

# Create the first admin from DJANGO_SUPERUSER_* env vars; skip if it exists.
if [ "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py createsuperuser --noinput \
    --username "${DJANGO_SUPERUSER_USERNAME:-admin}" \
    --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}" || true
fi
