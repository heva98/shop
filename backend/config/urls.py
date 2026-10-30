"""URL configuration for the Shop ERP backend.

Every app's DRF router is mounted under /api/<app>/ — see each app's urls.py
for its endpoints.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core.auth_views import obtain_token
from core.health import health

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth-token/', obtain_token),
    path('api/health/', health),
    path('api/core/', include('core.urls')),
    path('api/platform/', include('core.platform_urls')),
    path('api/catalog/', include('catalog.urls')),
    path('api/inventory/', include('inventory.urls')),
    path('api/receiving/', include('receiving.urls')),
    path('api/enquiry/', include('enquiry.urls')),
    path('api/pos/', include('pos.urls')),
    path('api/payments/', include('payments.urls')),
    path('api/pricing/', include('pricing.urls')),
    path('api/credit/', include('credit.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/analytics/', include('analytics.urls')),
    path('api/reports/', include('reports.urls')),
    path('api/imports/', include('imports.urls')),
    path('api/audit/', include('audit.urls')),
]

if settings.DEBUG:
    # In production nginx serves MEDIA_ROOT directly (see deploy/nginx/);
    # this is only for `manage.py runserver` during development.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
