from django.contrib import admin

from .models import SavedVisualization


@admin.register(SavedVisualization)
class SavedVisualizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'entity', 'created_by', 'shared')
    list_filter = ('type', 'shared')
