from django.contrib import admin

from .models import Bundle, Price, Promotion


@admin.register(Price)
class PriceAdmin(admin.ModelAdmin):
    list_display = ('product', 'entity', 'store', 'unit_price', 'updated_at')
    list_filter = ('entity', 'store')


@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    list_display = ('name', 'entity', 'price')
    list_filter = ('entity',)
    filter_horizontal = ('products',)


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ('name', 'product', 'store', 'promo_price', 'starts_on', 'ends_on', 'is_active')
    list_filter = ('entity', 'store', 'is_active')
    search_fields = ('name', 'product__name')
