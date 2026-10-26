from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('payment-methods', views.PaymentMethodViewSet)

urlpatterns = router.urls
