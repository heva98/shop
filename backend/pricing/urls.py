from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('prices', views.PriceViewSet)
router.register('bundles', views.BundleViewSet)
router.register('promotions', views.PromotionViewSet)

urlpatterns = router.urls
