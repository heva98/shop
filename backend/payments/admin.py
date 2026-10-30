from django.contrib import admin

from .models import EntityPaymentMethod, PaymentMethod


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('name', 'implementation', 'is_active')


@admin.register(EntityPaymentMethod)
class EntityPaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('method', 'entity', 'is_active')
    list_filter = ('method', 'is_active')
