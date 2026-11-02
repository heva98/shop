"""The API answers in the language the app asks for (Accept-Language)."""
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditEvent
from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Role, Store, StoreRole, User

SW = {'HTTP_ACCEPT_LANGUAGE': 'sw'}


class ApiLanguageTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='Main')
        self.admin = User.objects.create_user(username='admin', password='Admin-pass-123', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)

    def test_wrong_password_in_swahili(self):
        response = self.client.post('/api/auth-token/', {'username': 'admin', 'password': 'nope'}, **SW)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['non_field_errors'], ['Imeshindwa kuingia kwa taarifa ulizotoa.'])

    def test_english_stays_the_default(self):
        response = self.client.post('/api/auth-token/', {'username': 'admin', 'password': 'nope'})
        self.assertEqual(response.data['non_field_errors'], ['Unable to log in with provided credentials.'])

    def test_rest_framework_messages_in_swahili(self):
        response = self.client.get('/api/core/users/me/', **SW)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['detail'], 'Taarifa za kuingia hazikutolewa.')

    def test_choice_labels_in_swahili(self):
        self.client.force_authenticate(self.admin)
        self.client.post('/api/auth-token/', {'username': 'admin', 'password': 'Admin-pass-123'})
        response = self.client.get('/api/audit/events/', **SW)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['results'][0]['action_label'], 'Ameingia')

    def test_activity_log_summary_follows_the_reader(self):
        """Stored in English, shown in each reader's language."""
        self.client.force_authenticate(self.admin)
        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Piece', unit_value=1)
        response = self.client.post('/api/catalog/products/', {
            'entity': self.entity.id, 'name': 'Sugar 1kg', 'uom': uom.id, 'vat_class': 'standard',
        }, **SW)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        event = AuditEvent.objects.get(action=AuditEvent.Action.PRODUCT_CREATED)
        self.assertEqual(event.summary, 'Product Sugar 1kg added')
        sw = self.client.get('/api/audit/events/', **SW).data['results'][0]
        en = self.client.get('/api/audit/events/').data['results'][0]
        self.assertEqual(sw['summary'], 'Bidhaa Sugar 1kg imeongezwa')
        self.assertEqual(en['summary'], 'Product Sugar 1kg added')
        self.assertTrue(Product.objects.filter(name='Sugar 1kg').exists())

    def test_screens_built_from_translated_labels_work_in_swahili(self):
        """Labels translated lazily must still reach Excel templates and JSON."""
        self.client.force_authenticate(self.admin)
        kinds = self.client.get('/api/imports/', **SW)
        self.assertEqual(kinds.status_code, status.HTTP_200_OK)
        self.assertIn('Bidhaa', [k['title'] for k in kinds.data])
        for kind in kinds.data:
            template = self.client.get(f"/api/imports/{kind['key']}/template/", **SW)
            self.assertEqual(template.status_code, status.HTTP_200_OK, kind['key'])
        catalogue = self.client.get('/api/analytics/dimensions/', **SW)
        self.assertEqual(catalogue.status_code, status.HTTP_200_OK)
        labels = {d['id']: d['label'] for d in catalogue.data['dimensions']}
        self.assertEqual(labels['pe'], 'Kipindi')
        features = self.client.get('/api/core/features/', **SW)
        self.assertEqual(features.status_code, status.HTTP_200_OK)
        self.assertIn('Mauzo kwa mkopo', [f['label'] for f in features.data['features']])

    def test_language_is_saved_on_the_profile(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch('/api/core/users/me/', {'language': 'sw'})
        self.assertEqual(response.data['language'], 'sw')
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.language, 'sw')


class CatalogueTests(TestCase):
    def test_compiled_catalogue_matches_the_source(self):
        """locale/sw/LC_MESSAGES/django.mo is rebuilt from django.po."""
        from pathlib import Path

        from django.conf import settings

        from core.management.commands.compile_translations import parse_po
        import gettext

        po = Path(settings.BASE_DIR) / 'locale/sw/LC_MESSAGES/django.po'
        compiled = gettext.GNUTranslations(open(po.with_suffix('.mo'), 'rb'))._catalog
        for msgid, msgstr in parse_po(po.read_text(encoding='utf-8')).items():
            if msgid and '\0' not in msgid:
                self.assertEqual(compiled.get(msgid), msgstr, msgid)
