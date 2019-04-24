#!/bin/sh

export WORKDIR=/srv/www/ClinicApp/clinicapp/

check_connection() {
value=$(python $WORKDIR/manage.py shell -c "
from django.db import connections
from django.db.utils import OperationalError
import os
db_conn, connected = connections['default'], 1
try:
    c = db_conn.cursor()
except OperationalError:
    connected = 0
print('%s' % connected)
")
return $value
}

while true; do
    check_connection
    if [ "$?" = 1 ]
    then
        echo 'database exists'
        break
    else
        echo 'database not exists yet'
        sleep 1s
    fi
done

python $WORKDIR/manage.py migrate
python $WORKDIR/manage.py collectstatic --noinput

create_superuser="
from django.contrib.auth import get_user_model

User = get_user_model()

try:
    if not User.objects.filter(email='$DJANGO_SUPERUSER_MAIL').exists():
        User.objects.create_superuser(
            '$DJANGO_SUPERUSER_MAIL', '$DJANGO_SUPERUSER_PASS',
            username='$DJANGO_SUPERUSER_NAME'
        )
except Exception as e:
    print(e)
"

create_superuser() {
    if [ -z "$DJANGO_SUPERUSER_NAME" ] || [ -z "$DJANGO_SUPERUSER_MAIL" ] || [ -z "$DJANGO_SUPERUSER_PASS" ]; then
        echo "Environment variables for superuser not set, not creating superuser."
    else
        echo "Creating superuser"
        python $WORKDIR/manage.py shell -c "$create_superuser"
    fi
}

create_superuser

uwsgi --http :8000 --module clinicapp.wsgi
