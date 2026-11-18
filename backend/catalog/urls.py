from django.urls import path
from rest_framework.routers import DefaultRouter

from . import setup, views

router = DefaultRouter()
router.register('categories', views.CategoryViewSet)
router.register('generic-drugs', views.GenericDrugViewSet)
router.register('units-of-measure', views.UnitOfMeasureViewSet)
router.register('products', views.ProductViewSet)

urlpatterns = [path('quick-add/', setup.quick_add), path('getting-started/', setup.getting_started)] + router.urls
