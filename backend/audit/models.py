from django.conf import settings
from django.db import models

from core.models import Entity, Store


class AuditEvent(models.Model):
    """Append-only record of who did something sensitive, and when: price
    changes, voids, write-offs, stock-count approvals, staff and role
    changes, imports, sign-ins (including failed ones). Never edited or
    deleted — there is no write API, and the admin is read-only."""

    class Action(models.TextChoices):
        LOGIN = 'login', 'Signed in'
        LOGIN_FAILED = 'login_failed', 'Failed sign-in'
        LOGIN_LOCKED = 'login_locked', 'Sign-in locked out'
        PRICE_SET = 'price_set', 'Price set'
        PRICE_REMOVED = 'price_removed', 'Price removed'
        PRODUCT_CREATED = 'product_created', 'Product added'
        PRODUCT_UPDATED = 'product_updated', 'Product changed'
        SALE_VOIDED = 'sale_voided', 'Sale voided'
        OFFLINE_SALE_PRICE = 'offline_sale_price', 'Offline sale at an old price'
        SHIFT_CLOSED = 'shift_closed', 'Shift closed'
        STOCK_WRITTEN_OFF = 'stock_written_off', 'Stock written off'
        STOCK_COUNT_APPROVED = 'stock_count_approved', 'Stock count approved'
        INVOICE_RECEIVED = 'invoice_received', 'Supplier invoice received'
        SUPPLIER_PAYMENT = 'supplier_payment', 'Supplier payment recorded'
        USER_CREATED = 'user_created', 'User created'
        USER_UPDATED = 'user_updated', 'User changed'
        USER_DISABLED = 'user_disabled', 'User disabled'
        USER_ENABLED = 'user_enabled', 'User enabled'
        PASSWORD_RESET = 'password_reset', 'Password reset by admin'
        PASSWORD_CHANGED = 'password_changed', 'Password changed'
        ROLE_GRANTED = 'role_granted', 'Role granted'
        ROLE_REMOVED = 'role_removed', 'Role removed'
        PAYMENT_METHOD_CHANGED = 'payment_method_changed', 'Payment method switched on/off'
        SETTINGS_CHANGED = 'settings_changed', 'Settings changed'
        DATA_IMPORTED = 'data_imported', 'Data imported'
        TRANSFER_SENT = 'transfer_sent', 'Stock sent to another store'
        TRANSFER_RECEIVED = 'transfer_received', 'Stock received from another store'
        TRANSFER_RESOLVED = 'transfer_resolved', 'Short delivery resolved'
        TRANSFER_CANCELLED = 'transfer_cancelled', 'Transfer cancelled'
        TRANSFER_PAID = 'transfer_paid', 'Branch payment recorded'
        CUSTOMER_CHANGED = 'customer_changed', 'Customer added or changed'
        CREDIT_PAYMENT = 'credit_payment', 'Customer credit payment received'
        CREDIT_PAYMENT_VOIDED = 'credit_payment_voided', 'Customer credit payment voided'
        DISCOUNT_GIVEN = 'discount_given', 'Discount over the cashier limit'
        PROMOTION_CHANGED = 'promotion_changed', 'Promotion added or changed'
        SHOP_REGISTERED = 'shop_registered', 'Shop registered'
        SHOP_SUSPENDED = 'shop_suspended', 'Shop suspended'
        SHOP_REACTIVATED = 'shop_reactivated', 'Shop reactivated'

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
