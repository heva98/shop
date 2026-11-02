from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('logs', views.NotificationLogViewSet)
router.register('sms/templates', views.SmsTemplateViewSet, basename='sms-template')
router.register('sms/batches', views.SmsBatchViewSet, basename='sms-batch')

urlpatterns = [
    path('settings/', views.notification_settings),
    path('test-sms/', views.test_sms),
    path('sms/config/', views.sms_config),
    path('sms/preview/', views.sms_preview),
    path('sms/send/', views.sms_send),
    *router.urls,
]
