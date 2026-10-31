from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html

from .models import Entity, ModuleEnablement, ModuleRegistry, Store, StoreRole, User

_PROFILE_FIELDS = ('middle_name', 'gender', 'date_of_birth')


@admin.register(User)
class ShopUserAdmin(UserAdmin):
    list_display = ('username', 'first_name', 'last_name', 'entity', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('Profile', {'fields': ('entity',) + _PROFILE_FIELDS}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
        ('Personal info', {
            'classes': ('wide',),
            'fields': ('first_name', 'middle_name', 'last_name', 'gender', 'date_of_birth',
                       'email', 'entity'),
        }),
    )


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ('name', 'tin', 'main_store', 'price_mode', 'logo_preview')
    readonly_fields = ('logo_preview',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.ensure_single_store()

    @admin.display(description='Logo')
    def logo_preview(self, entity):
        if not entity.logo:
            return '—'
        return format_html('<img src="{}" style="height:32px;width:auto;">', entity.logo.url)


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'entity', 'address', 'is_active')
    list_filter = ('is_active', 'entity')


@admin.register(StoreRole)
class StoreRoleAdmin(admin.ModelAdmin):
    list_display = ('user', 'store', 'role')
    list_filter = ('role', 'store')


@admin.register(ModuleRegistry)
class ModuleRegistryAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'scope', 'implements')


@admin.register(ModuleEnablement)
class ModuleEnablementAdmin(admin.ModelAdmin):
    list_display = ('module', 'entity', 'store', 'enabled')
    list_filter = ('enabled', 'module')
