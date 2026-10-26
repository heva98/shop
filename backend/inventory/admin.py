from django.contrib import admin

from .models import StockAdjustment, StockBatch, StockCount, StockCountLine, StockLedger, StoreProduct


@admin.register(StoreProduct)
class StoreProductAdmin(admin.ModelAdmin):
    list_display = ('store', 'product', 'enabled', 'reorder_level')
    list_filter = ('enabled', 'store')


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = ('product', 'store', 'batch_no', 'expiry_date', 'qty_on_hand')
    list_filter = ('store',)
    search_fields = ('batch_no', 'product__name')


@admin.register(StockLedger)
class StockLedgerAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'store', 'batch', 'ledger_type', 'qty_delta', 'ref_type', 'ref_id')
    list_filter = ('ledger_type', 'store')
    readonly_fields = [f.name for f in StockLedger._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False


class _ReadOnlyAdmin(admin.ModelAdmin):
    """Stock records only change through the app's own rules (manager
    approval, the ledger); the admin is for looking, not editing."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(_ReadOnlyAdmin):
    list_display = ('created_at', 'store', 'batch', 'reason', 'qty_delta', 'created_by', 'note')
    list_filter = ('reason', 'store')


class StockCountLineInline(admin.TabularInline):
    model = StockCountLine
    extra = 0
    can_delete = False
    readonly_fields = ('product', 'batch_no', 'expiry_date', 'expected_qty', 'counted_qty', 'adjustment_qty')
    fields = readonly_fields


@admin.register(StockCount)
class StockCountAdmin(_ReadOnlyAdmin):
    list_display = ('created_at', 'store', 'status', 'created_by', 'approved_by')
    list_filter = ('status', 'store')
    inlines = [StockCountLineInline]
