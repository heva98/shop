from django.contrib import admin

from .models import Customer, CustomerPayment


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'entity', 'credit_limit', 'is_active')
    list_filter = ('is_active', 'entity')
    search_fields = ('name', 'phone')


@admin.register(CustomerPayment)
class CustomerPaymentAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'customer', 'store', 'amount', 'payment_method', 'voided_at')
    list_filter = ('payment_method', 'store')
    search_fields = ('customer__name', 'reference')
    readonly_fields = [f.name for f in CustomerPayment._meta.fields]
