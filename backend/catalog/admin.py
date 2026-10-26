from django.contrib import admin

from .models import Category, Product, UnitOfMeasure


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name')
    search_fields = ('name', 'short_name')


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit_value', 'description')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'brand', 'size', 'vat_class', 'uom', 'barcode', 'tracks_expiry')
    list_filter = ('category', 'vat_class', 'tracks_expiry')
    search_fields = ('name', 'short_name')
