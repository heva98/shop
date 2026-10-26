from rest_framework import status
from rest_framework.test import APITestCase

from core.features import set_feature
from core.models import Entity, Role, Store, StoreRole, User

from .models import SavedVisualization

URL = '/api/analytics/visualizations/'


def config(**overrides):
    return {
        'version': 1, 'type': 'PIVOT_TABLE', 'columns': ['dx'], 'rows': ['pe'], 'filters': ['ou'],
        'items': {'dx': ['sales.net'], 'pe': ['LAST_12_MONTHS'], 'ou': ['FIRM']}, 'options': {},
        **overrides,
    }


class SavedVisualizationTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        Store.objects.create(entity=self.entity, name='Main')
        self.owner = self.admin('owner', self.entity)
        self.colleague = self.admin('colleague', self.entity)
        self.outsider = self.admin('outsider', Entity.objects.create(name='Firm B'))
        self.client.force_authenticate(self.owner)

    def admin(self, username, entity):
        user = User.objects.create_user(username=username, password='x', entity=entity)
        StoreRole.objects.create(user=user, store=None, role=Role.ENTITY_ADMIN)
        return user

    def create(self, **data):
        response = self.client.post(URL, {'name': 'Monthly sales', 'config': config(), **data}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data

    def names(self, user, **params):
        self.client.force_authenticate(user)
        return [v['name'] for v in self.client.get(URL, params).data]

    def test_create_takes_type_from_config(self):
        viz = self.create(config=config(type='LINE'))
        self.assertEqual(viz['type'], 'LINE')
        self.assertTrue(viz['is_owner'])
        self.assertEqual(SavedVisualization.objects.get().entity, self.entity)

    def test_shared_only_within_the_firm(self):
        self.create(name='Private')
        self.create(name='Shared', shared=True)
        self.assertEqual(self.names(self.colleague), ['Shared'])
        self.assertEqual(self.names(self.outsider), [])

    def test_only_the_creator_may_change_it(self):
        viz = self.create(shared=True)
        self.client.force_authenticate(self.colleague)
        self.assertEqual(self.client.patch(f'{URL}{viz["id"]}/', {'name': 'Mine'}, format='json').status_code,
                         status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.delete(f'{URL}{viz["id"]}/').status_code, status.HTTP_403_FORBIDDEN)

    def test_pin_and_unshare(self):
        viz = self.create(shared=True)
        self.client.force_authenticate(self.colleague)
        self.assertEqual(self.client.post(f'{URL}{viz["id"]}/pin/').status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.names(self.colleague, pinned='true'), ['Monthly sales'])
        # Unsharing takes it off the colleague's dashboard.
        self.client.force_authenticate(self.owner)
        self.client.patch(f'{URL}{viz["id"]}/', {'shared': False}, format='json')
        self.assertEqual(self.names(self.colleague, pinned='true'), [])

    def test_invalid_configs_are_refused(self):
        for bad in (config(type='MAP'), config(rows=['dx']), config(items={'dx': 'sales.net'}),
                    config(items={'dx': ['no.such.metric']})):
            response = self.client.post(URL, {'name': 'x', 'config': bad}, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, bad)

    def test_unavailable_after_a_feature_is_switched_off(self):
        viz = self.create(config=config(items={'dx': ['credit.given'], 'pe': ['THIS_YEAR'], 'ou': ['FIRM']}))
        set_feature('customer_credit', False, entity=self.entity)
        data = self.client.get(f'{URL}{viz["id"]}/').data
        self.assertEqual(data['unavailable'][0]['reason'], 'feature_disabled')
        self.assertEqual(data['unavailable'][0]['features'], ['Sales on credit'])
