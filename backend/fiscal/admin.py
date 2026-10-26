from django.contrib import admin

from .models import FiscalReceipt


@admin.register(FiscalReceipt)
class FiscalReceiptAdmin(admin.ModelAdmin):
    list_display = ('sale_id', 'driver', 'receipt_number', 'status', 'attempted_at')
    list_filter = ('driver', 'status')
