from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Entity, Role, Store, StoreRole, User

from .models import PaymentMethod


class PaymentMethodRoleTests(APITestCase):
    def setUp(self):
        entity = Entity.objects.create(name='Firm A')
        store = Store.objects.create(entity=entity, name='A')
        self.cashier = User.objects.create_user(username='cashier', password='x', entity=entity)
        StoreRole.objects.create(user=self.cashier, store=store, role=Role.CASHIER)
        self.admin = User.objects.create_user(username='admin', password='x', entity=entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)

    def test_cashier_cannot_toggle_a_payment_method(self):
        pm = PaymentMethod.objects.create(
            name='Mobile Money', implementation=PaymentMethod.Implementation.MOBILE_MONEY, is_active=False,
        )
        self.client.force_authenticate(self.cashier)
        response = self.client.patch(f'/api/payments/payment-methods/{pm.id}/', {'is_active': True})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_entity_admin_can_toggle_a_payment_method(self):
        pm = PaymentMethod.objects.create(
            name='Mobile Money', implementation=PaymentMethod.Implementation.MOBILE_MONEY, is_active=False,
        )
        self.client.force_authenticate(self.admin)
        response = self.client.patch(f'/api/payments/payment-methods/{pm.id}/', {'is_active': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
