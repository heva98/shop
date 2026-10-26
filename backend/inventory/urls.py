from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('store-products', views.StoreProductViewSet)
router.register('batches', views.StockBatchViewSet)
router.register('ledger', views.StockLedgerViewSet)
router.register('adjustments', views.StockAdjustmentViewSet)
router.register('stock-counts', views.StockCountViewSet)

urlpatterns = router.urls
