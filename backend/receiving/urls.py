from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('suppliers', views.SupplierViewSet)
router.register('invoices', views.ReceivingInvoiceViewSet)
router.register('invoice-lines', views.ReceivingInvoiceLineViewSet)

urlpatterns = router.urls
