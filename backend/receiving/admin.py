from django.contrib import admin

from .models import ReceivingInvoice, ReceivingInvoiceLine, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'entity', 'location', 'email', 'phone')
    list_filter = ('entity',)


class ReceivingInvoiceLineInline(admin.TabularInline):
    model = ReceivingInvoiceLine
    extra = 0


@admin.register(ReceivingInvoice)
class ReceivingInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'store', 'supplier', 'received_date', 'status')
    list_filter = ('status', 'store', 'supplier')
    inlines = [ReceivingInvoiceLineInline]
