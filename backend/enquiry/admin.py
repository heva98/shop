from django.contrib import admin

from .models import Enquiry, EnquiryLine, Transfer, TransferLine


class EnquiryLineInline(admin.TabularInline):
    model = EnquiryLine
    extra = 0


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ('id', 'requesting_store', 'mode', 'target_store', 'status', 'created_at')
    list_filter = ('mode', 'status')
    inlines = [EnquiryLineInline]


class TransferLineInline(admin.TabularInline):
    model = TransferLine
    extra = 0


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ('id', 'from_store', 'to_store', 'mode', 'status', 'dispatched_at')
    list_filter = ('mode', 'status')
    inlines = [TransferLineInline]
