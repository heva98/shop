from django.contrib import admin

from .models import ControlledSubstanceEntry


@admin.register(ControlledSubstanceEntry)
class ControlledSubstanceEntryAdmin(admin.ModelAdmin):
    list_display = ('recorded_at', 'store', 'product', 'kind', 'qty', 'patient_name', 'prescriber_name')
    list_filter = ('store', 'kind')
    search_fields = ('patient_name', 'prescriber_name', 'prescription_ref', 'product__name')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
