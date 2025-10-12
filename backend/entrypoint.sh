#!/bin/sh
set -e

if [ "${SKIP_MIGRATE}" != "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${SKIP_COLLECTSTATIC}" != "1" ]; then
  python manage.py collectstatic --noinput
fi

exec "$@"
