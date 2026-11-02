from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy

from core.models import Entity, Store


class AuditEvent(models.Model):
    """Append-only record of who did something sensitive, and when: price
    changes, voids, write-offs, stock-count approvals, staff and role
    changes, imports, sign-ins (including failed ones). Never edited or
    deleted — there is no write API, and the admin is read-only."""

    class Action(models.TextChoices):
        LOGIN = 'login', gettext_lazy('Signed in')
        LOGIN_FAILED = 'login_failed', gettext_lazy('Failed sign-in')
        LOGIN_LOCKED = 'login_locked', gettext_lazy('Sign-in locked out')
        PRICE_SET = 'price_set', gettext_lazy('Price set')
        PRICE_REMOVED = 'price_removed', gettext_lazy('Price removed')
        PRODUCT_CREATED = 'product_created', gettext_lazy('Product added')
        PRODUCT_UPDATED = 'product_updated', gettext_lazy('Product changed')
        SALE_VOIDED = 'sale_voided', gettext_lazy('Sale voided')
        OFFLINE_SALE_PRICE = 'offline_sale_price', gettext_lazy('Offline sale at an old price')
        SHIFT_CLOSED = 'shift_closed', gettext_lazy('Shift closed')
        STOCK_WRITTEN_OFF = 'stock_written_off', gettext_lazy('Stock written off')
        STOCK_COUNT_APPROVED = 'stock_count_approved', gettext_lazy('Stock count approved')
        INVOICE_RECEIVED = 'invoice_received', gettext_lazy('Supplier invoice received')
        SUPPLIER_PAYMENT = 'supplier_payment', gettext_lazy('Supplier payment recorded')
        USER_CREATED = 'user_created', gettext_lazy('User created')
        USER_UPDATED = 'user_updated', gettext_lazy('User changed')
        USER_DISABLED = 'user_disabled', gettext_lazy('User disabled')
        USER_ENABLED = 'user_enabled', gettext_lazy('User enabled')
        PASSWORD_RESET = 'password_reset', gettext_lazy('Password reset by admin')
        PASSWORD_CHANGED = 'password_changed', gettext_lazy('Password changed')
        ROLE_GRANTED = 'role_granted', gettext_lazy('Role granted')
        ROLE_REMOVED = 'role_removed', gettext_lazy('Role removed')
        PAYMENT_METHOD_CHANGED = 'payment_method_changed', gettext_lazy('Payment method switched on/off')
        SETTINGS_CHANGED = 'settings_changed', gettext_lazy('Settings changed')
        DATA_IMPORTED = 'data_imported', gettext_lazy('Data imported')
        TRANSFER_SENT = 'transfer_sent', gettext_lazy('Stock sent to another store')
        TRANSFER_RECEIVED = 'transfer_received', gettext_lazy('Stock received from another store')
        TRANSFER_RESOLVED = 'transfer_resolved', gettext_lazy('Short delivery resolved')
        TRANSFER_CANCELLED = 'transfer_cancelled', gettext_lazy('Transfer cancelled')
        TRANSFER_PAID = 'transfer_paid', gettext_lazy('Branch payment recorded')
        CUSTOMER_CHANGED = 'customer_changed', gettext_lazy('Customer added or changed')
        CREDIT_PAYMENT = 'credit_payment', gettext_lazy('Customer credit payment received')
        CREDIT_PAYMENT_VOIDED = 'credit_payment_voided', gettext_lazy('Customer credit payment voided')
        DISCOUNT_GIVEN = 'discount_given', gettext_lazy('Discount over the cashier limit')
        PROMOTION_CHANGED = 'promotion_changed', gettext_lazy('Promotion added or changed')
        SHOP_REGISTERED = 'shop_registered', gettext_lazy('Shop registered')
        SHOP_SUSPENDED = 'shop_suspended', gettext_lazy('Shop suspended')
        SHOP_REACTIVATED = 'shop_reactivated', gettext_lazy('Shop reactivated')

    id = models.BigAutoField(primary_key=True)
    entity = models.ForeignKey(Entity, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    store = models.ForeignKey(Store, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    username = models.CharField(
        max_length=150, blank=True,
        help_text='Kept even if the user is later removed, and for failed sign-ins.')
    action = models.CharField(max_length=32, choices=Action.choices)
    summary = models.CharField(max_length=255)
    data = models.JSONField(default=dict, blank=True)
    ip_address = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['entity', 'created_at']),
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['username', 'created_at']),
        ]

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} {self.username} {self.action}'
