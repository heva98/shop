"""Architecture fitness tests: the dependency rules of architecture.txt,
checked on every test run so they can't quietly erode.

    kernel   core, catalog, inventory, sync — always installed; depends on
             nothing outside the kernel (audit, the cross-cutting activity
             log, aside)
    modules  pluggable apps; depend on the kernel and, where a feature
             really spans them, on each other
    onboarding  composes modules; nothing depends on it

Within an app: models hold data, services change it, views adapt HTTP.
Models never reach up into services or views, and pure domain rules
never touch the database.

Every import is checked, including the ones inside functions (the usual
way to hide a cycle). Tests, migrations and management commands are left
out: they may assemble anything."""

import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)
KERNEL = {'core', 'catalog', 'inventory', 'sync'}
CROSS_CUTTING = {'audit'}
COMPOSITION = {'onboarding'}
MODULES = {'receiving', 'enquiry', 'pos', 'fiscal', 'payments', 'notifications', 'credit',
           'controlled_substances', 'pricing', 'analytics', 'reports', 'imports'}
APPS = KERNEL | CROSS_CUTTING | COMPOSITION | MODULES
USE_CASE_LAYERS = ['pos/services', 'credit/services.py', 'onboarding/services.py', 'inventory/services',
                   'inventory/stock.py', 'enquiry/services', 'receiving/services.py']
# Apps whose models hold data only: every workflow is in their services.
LAYERED_APPS = ['pos', 'credit', 'inventory', 'enquiry', 'receiving']


def _source_files(app):
    for path in (BASE / app).rglob('*.py'):
        parts = path.relative_to(BASE).parts
        if 'migrations' in parts or 'management' in parts or path.name.startswith('test'):
            continue
        yield path


def _imports(path):
    """(line, absolute dotted module) for every import in the file."""
    package = '.'.join(path.relative_to(BASE).with_suffix('').parts[:-1])
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split('.')[:len(package.split('.')) - node.level + 1]
                module = '.'.join(base + ([node.module] if node.module else []))
            else:
                module = node.module
            yield node.lineno, module
            for alias in node.names:  # `from . import services`
                yield node.lineno, f'{module}.{alias.name}'


def _violations(apps, forbidden):
    """'file:line imports module' for each import, in `apps`, of a module
    `forbidden(importing_app, module)` says is not allowed."""
    found = []
    for app in apps:
        for path in _source_files(app):
            for line, module in _imports(path):
                if forbidden(app, module):
                    found.append(f'{path.relative_to(BASE)}:{line} imports {module}')
    return sorted(set(found))


def _app(module):
    return module.split('.')[0]


class DependencyRuleTests(SimpleTestCase):
    def test_every_app_is_classified(self):
        installed = {name for name in settings.INSTALLED_APPS if '.' not in name and (BASE / name).is_dir()}
        self.assertEqual(installed - APPS, set(), 'Classify the new app in core/test_architecture.py')

    def test_kernel_depends_on_no_module(self):
        self.assertEqual(_violations(KERNEL, lambda app, m: _app(m) in MODULES | COMPOSITION), [])

    def test_nothing_depends_on_composition(self):
        self.assertEqual(_violations(KERNEL | MODULES | CROSS_CUTTING, lambda app, m: _app(m) in COMPOSITION), [])

    def test_selling_does_not_know_the_pharmacy_register(self):
        # The register listens to pos.events instead (dependency inversion).
        self.assertEqual(_violations({'pos'}, lambda app, m: _app(m) == 'controlled_substances'), [])

    def test_exception_handler_knows_only_the_base_error(self):
        imports = {m for _, m in _imports(BASE / 'config' / 'exceptions.py')}
        self.assertEqual({m for m in imports if _app(m) in APPS}, {'core.errors', 'core.errors.DomainError'})


class LayerRuleTests(SimpleTestCase):
    def test_models_never_reach_up_into_services_or_views(self):
        def forbidden(app, module):
            return module.split('.')[-1] in {'services', 'views', 'serializers'} or '.services.' in module

        found = []
        for app in APPS:
            path = BASE / app / 'models.py'
            if path.exists():
                found += [f'{app}/models.py:{line} imports {m}' for line, m in _imports(path) if forbidden(app, m)]
        self.assertEqual(found, [])

    def test_layered_models_run_no_workflows(self):
        """A model that opens a transaction is running a workflow; that
        belongs in the app's services."""
        found = [f'{app}/models.py:{line} imports {m}' for app in LAYERED_APPS
                 for line, m in _imports(BASE / app / 'models.py') if m.startswith('django.db.transaction')]
        self.assertEqual(found, [])

    def test_stock_moves_only_through_the_stock_api(self):
        """Nobody writes ledger rows or batch quantities except
        inventory.stock.record_movement."""
        found = []
        for app in APPS:
            for path in _source_files(app):
                if path == BASE / 'inventory' / 'stock.py':
                    continue
                text = path.read_text(encoding='utf-8')
                for needle in ('StockLedger.objects.create', 'qty_on_hand=F(', 'StockLedger.record('):
                    if needle in text:
                        found.append(f'{path.relative_to(BASE)} uses {needle}')
        self.assertEqual(found, [])

    def test_pos_domain_rules_touch_no_database_or_http(self):
        path = BASE / 'pos' / 'domain.py'
        bad = [m for _, m in _imports(path)
               if m.startswith(('django.db', 'rest_framework')) or m.startswith('pos.models')]
        self.assertEqual(bad, [])

    def test_use_cases_know_nothing_of_http(self):
        """Services take plain values and model objects, never a DRF
        request or serializer, so a management command, a test or a sync
        job can run the same use case as a view."""
        found = []
        for layer in USE_CASE_LAYERS:
            path = BASE / layer
            for file in (path.rglob('*.py') if path.is_dir() else [path]):
                found += [f'{file.relative_to(BASE)}:{line} imports {m}' for line, m in _imports(file)
                          if m.startswith('rest_framework')]
        self.assertEqual(found, [])
