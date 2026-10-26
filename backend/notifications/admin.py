from django.contrib import admin

from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('store', 'kind', 'channel', 'success', 'sent_at')
    list_filter = ('kind', 'channel', 'success')
