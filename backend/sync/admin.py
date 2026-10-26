from django.contrib import admin

from .models import SyncOutbox


@admin.register(SyncOutbox)
class SyncOutboxAdmin(admin.ModelAdmin):
    list_display = ('content_type', 'object_id', 'store_id', 'status', 'attempts', 'created_at')
    list_filter = ('status', 'content_type')
