#!/bin/sh
set -e

if [ "${SKIP_COLLECTSTATIC}" != "1" ]; then
  python manage.py collectstatic --noinput
fi

exec "$@"
