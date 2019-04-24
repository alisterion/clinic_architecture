"""clinicapp URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.10/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.conf.urls import url, include
    2. Add a URL to urlpatterns:  url(r'^blog/', include('blog.urls'))
"""
from django.conf.urls import url, include
from django.conf.urls.static import static
from django.conf import settings
from django.contrib import admin
from rest_framework_swagger.views import get_swagger_view

from clinicapp.pkg.users.views import check_token_view
from clinicapp.pkg.common.views import websocket_documentation

schema_view = get_swagger_view(title='Clinic App API')

urlpatterns = [
    url(r'^$', schema_view),
    url(r'^api-docs/ws$', websocket_documentation),
    url(r'^admin/', admin.site.urls),
    url(r'', include('social_django.urls', namespace='social')),
    url(r'^api-auth/', include('rest_framework.urls',
                               namespace='rest_framework')),
    url(r'^api/v1/', include('clinicapp.pkg.users.urls')),
    url(r'^api/v1/', include('clinicapp.pkg.clinics.urls')),
    url(r'^api/v1/', include('clinicapp.pkg.diagnoses.urls')),
    url(r'^api/v1/', include('clinicapp.pkg.appointments.urls')),
    url(r'^api/v1/', include('clinicapp.pkg.payments.urls')),
    url(r'^api/v1/', include('clinicapp.pkg.common.urls')),
    url(r'^api/v1/', include('clinicapp.pkg.notifications.urls')),
    url(r'^confirm_invite/token/(?P<token>[^/.]+)$', check_token_view),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL, document_root=settings.MEDIA_ROOT
    )
