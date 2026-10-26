"""GET  /api/imports/                       the import kinds and their columns
GET  /api/imports/<kind>/template/        a CSV with the headers and an example row
POST /api/imports/<kind>/                 multipart {file, store?, commit?}

Without commit=true the import is a preview: everything is validated and
applied, then rolled back, and the response says what would happen.
"""

import csv
import io

from django.http import HttpResponse
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit.services import Action, record
from core.models import Entity, Role, Store
from core.permissions import is_store_manager, roles
from core.serializers import validate_accessible_store

from .importers import IMPORTERS
from .parsing import ImportFileError, read_rows

_MAX_BYTES = 5 * 1024 * 1024


def _importer_class(kind):
    cls = IMPORTERS.get(kind)
    if cls is None:
        raise NotFound(f'Unknown import "{kind}".')
    return cls


def _describe(cls):
    return {
        'key': cls.key, 'title': cls.title, 'description': cls.description, 'needs_store': cls.needs_store,
        'columns': [{'name': c.name, 'help': c.help, 'example': c.example, 'required': c.required} for c in cls.columns],
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def kinds(request):
    return Response([_describe(cls) for cls in IMPORTERS.values()])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def template(request, kind):
    cls = _importer_class(kind)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([c.name for c in cls.columns])
    writer.writerow([c.example for c in cls.columns])
    response = HttpResponse('﻿' + out.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{kind}-template.csv"'
    return response


@api_view(['POST'])
@permission_classes([roles(Role.STORE_MANAGER, Role.ENTITY_ADMIN)])
@parser_classes([MultiPartParser, FormParser])
def run_import(request, kind):
    cls = _importer_class(kind)
    user = request.user
    entity = user.entity if not user.is_superuser else None
    store = None
    if request.data.get('store'):
        store = Store.objects.filter(pk=request.data['store']).first()
        if store is None:
            raise ValidationError({'store': 'Unknown store.'})
        validate_accessible_store(store, request)
        entity = store.entity
    if entity is None:
        raise ValidationError({'store': 'Choose a store.'})
    entity = Entity.objects.get(pk=entity.pk)

    if cls.needs_store:
        if store is None:
            raise ValidationError({'store': 'Choose the store this stock is in.'})
        if not is_store_manager(user, store):
            raise PermissionDenied('Only a manager of this store can load its stock.')
    elif not (user.is_superuser or user.store_roles.filter(role=Role.ENTITY_ADMIN).exists()):
        raise PermissionDenied('Only an entity admin can import catalog data.')

    upload = request.FILES.get('file')
    if upload is None:
        raise ValidationError({'file': 'Attach a CSV or .xlsx file.'})
    if upload.size > _MAX_BYTES:
        raise ValidationError({'file': 'The file is larger than 5 MB. Split it into smaller files.'})
    try:
        headers, rows = read_rows(upload)
    except ImportFileError as e:
        raise ValidationError({'file': str(e)})

    importer = cls(entity=entity, store=store, user=user)
    missing = importer.missing_columns(headers)
    if missing:
        raise ValidationError({'file': f'Missing column(s): {", ".join(missing)}. Download the template to see the expected headers.'})

    commit = str(request.data.get('commit', '')).lower() in ('1', 'true', 'yes')
    result = importer.run(rows, commit=commit)
    if commit and not result.errors:
        record(Action.DATA_IMPORTED,
               f'{cls.title} imported from {upload.name}: {result.created} new, {result.updated} updated',
               request=request, store=store, entity=entity, data={'rows': result.rows})
    return Response({
        'committed': commit and not result.errors,
        'rows': result.rows, 'created': result.created, 'updated': result.updated,
        'errors': result.errors[:200], 'error_count': len(result.errors),
        'preview': result.preview,
        'ignored_columns': [h for h in headers if h and not any(h in (c.name,) + c.aliases for c in cls.columns)],
    })
