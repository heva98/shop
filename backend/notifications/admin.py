from django.contrib import admin

from .models import NotificationLog, SmsBatch, SmsConfiguration, SmsMessage, SmsTemplate


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('store', 'kind', 'channel', 'success', 'sent_at')
    list_filter = ('kind', 'channel', 'success')


@admin.register(SmsConfiguration)
class SmsConfigurationAdmin(admin.ModelAdmin):
    list_display = ('entity', 'language', 'daily_sales_to_managers', 'batch_recipient_cap', 'max_segments')


@admin.register(SmsTemplate)
class SmsTemplateAdmin(admin.ModelAdmin):
    list_display = ('entity', 'key', 'language', 'is_active', 'updated_at')
    list_filter = ('key', 'language', 'is_active')


class SmsMessageInline(admin.TabularInline):
    model = SmsMessage
    extra = 0
    fields = ('recipient_name', 'store', 'phone', 'status', 'skip_reason', 'error_detail', 'segments', 'sent_at')
    readonly_fields = fields
    can_delete = False


@admin.register(SmsBatch)
class SmsBatchAdmin(admin.ModelAdmin):
    list_display = ('entity', 'kind', 'status', 'sent_count', 'failed_count', 'skipped_count', 'created_at')
    list_filter = ('kind', 'status', 'dry_run')
    inlines = [SmsMessageInline]
