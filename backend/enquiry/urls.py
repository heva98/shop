from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('enquiries', views.EnquiryViewSet)
router.register('transfers', views.TransferViewSet)

urlpatterns = router.urls
