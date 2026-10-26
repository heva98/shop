from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('sales', views.SaleViewSet)
router.register('shifts', views.ShiftViewSet)

urlpatterns = [path('till/', views.TillSnapshotView.as_view(), name='till-snapshot'), *router.urls]
