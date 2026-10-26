from django.contrib import admin

from .models import Sale, SaleLine, Shift


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 0
    can_delete = False
    readonly_fields = ('batch', 'qty', 'unit_price', 'vat_class')


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    """Read-only: sales are financial records, corrected by voiding in the
    app, never by editing here."""
    list_display = ('number', 'store', 'status', 'cashier', 'payment_method', 'efd_receipt_no', 'completed_at')
    list_filter = ('store', 'status', 'payment_method')
    search_fields = ('efd_receipt_no', 'payment_reference', 'customer_name')
    inlines = [SaleLineInline]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('store', 'cashier', 'opened_at', 'closed_at', 'opening_float', 'expected_cash', 'counted_cash')
    list_filter = ('store',)
