from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('entities', views.EntityViewSet)
router.register('stores', views.StoreViewSet)
router.register('users', views.UserViewSet)
router.register('store-roles', views.StoreRoleViewSet)
router.register('modules', views.ModuleRegistryViewSet)
router.register('module-enablements', views.ModuleEnablementViewSet)

urlpatterns = [path('features/', views.features)] + router.urls
