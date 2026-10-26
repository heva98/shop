from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('logs', views.NotificationLogViewSet)

urlpatterns = [
    path('settings/', views.notification_settings),
    path('test-sms/', views.test_sms),
    *router.urls,
]
