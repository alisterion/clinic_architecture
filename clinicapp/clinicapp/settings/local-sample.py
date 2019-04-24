"""
Local settings. File must be named `local.py`.
In this file you must specify you credentials to db
and other variables like as DEBUG=True
"""

from .common import *

if 'test' not in sys.argv:
    DATABASES['default'].update({
        'USER': os.environ.get('POSTGRES_USER', 'user'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'password'),
    })

ALLOWED_HOSTS += ['127.0.0.1', 'project', ]
MIDDLEWARE += ['clinicapp.pkg.common.middleware.LoggingMiddleware', ]

FRONTEND_DOMAIN = 'clinicapp.com'
