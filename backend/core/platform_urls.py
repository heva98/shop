from rest_framework.routers import DefaultRouter

from . import platform

router = DefaultRouter()
router.register('shops', platform.ShopViewSet, basename='shop')

urlpatterns = router.urls
