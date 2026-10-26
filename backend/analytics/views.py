from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Exists, OuterRef, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from core.features import feature_enabled
from core.models import Role
from core.permissions import roles

from .models import SavedVisualization
from .query import QueryError, run_query
from .registry import Context, catalogue, visible_dimensions
from .serializers import SavedVisualizationSerializer

_ANALYTICS_ROLES = (Role.STORE_MANAGER, Role.ENTITY_ADMIN)


# ── Data Visualizer ────────────────────────────────────────────────────────

class _VisualizerView(APIView):
    permission_classes = [roles(*_ANALYTICS_ROLES), feature_enabled('analytics_dashboards')]


class DimensionsView(_VisualizerView):
    """GET /api/analytics/dimensions/: the metrics and dimensions the caller
    can query, filtered by the firm's features and the caller's stores."""

    def get(self, request):
        return Response(catalogue(Context.for_user(request.user)))


class AnalyticsQueryView(_VisualizerView):
    """GET /api/analytics/query/: aggregated values for metrics x periods x
    stores x other dimensions, in the DHIS2 /api/analytics shape. See
    `analytics.query` for the parameters."""

    def get(self, request):
        try:
            return Response(run_query(request.query_params, Context.for_user(request.user)))
        except QueryError as exc:
            return Response(exc.body, status=exc.status)


class DimensionItemsView(_VisualizerView):
    """GET /api/analytics/items/?dimension=product&search=soda&ids=<id>,<id>:
    items of a dimension too long to list in the catalogue (products,
    customers) matching the text, plus the given ids so a saved selection
    can be named."""

    def get(self, request):
        ctx = Context.for_user(request.user)
        visible = {d.id: d for d, _ in visible_dimensions(ctx)}
        dim = visible.get(request.query_params.get('dimension', ''))
        if dim is None or not dim.lazy:
            return Response({'detail': 'Unknown dimension.'}, status=status.HTTP_400_BAD_REQUEST)
        ids = [i for i in request.query_params.get('ids', '').split(',') if i]
        try:
            items = dim.search(ctx, request.query_params.get('search', '').strip(), ids)
        except DjangoValidationError:
            return Response({'detail': 'Invalid id.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(items)


class IsCreatorOrReadOnly(BasePermission):
    """A shared visualization is read-only to everyone but its creator; they
    can "save as" their own copy instead."""
    message = 'Only the person who saved this visualization can change it.'

    def has_object_permission(self, request, view, obj):
        return request.method in SAFE_METHODS or obj.created_by_id == request.user.id


class SavedVisualizationViewSet(viewsets.ModelViewSet):
    """/api/analytics/visualizations/: the caller's saved visualizations plus
    those colleagues in the same firm shared. `?pinned=true` lists the
    caller's dashboard widgets; `?search=` matches the name. POST/DELETE
    `<id>/pin/` pins or unpins one on the caller's own dashboard."""
    serializer_class = SavedVisualizationSerializer
    permission_classes = _VisualizerView.permission_classes + [IsCreatorOrReadOnly]
    # A firm has tens of these, and the Open dialog searches the whole list.
    pagination_class = None
    filter_backends = []

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'analytics': Context.for_user(self.request.user)}

    def get_queryset(self):
        user = self.request.user
        pinned = SavedVisualization.pinned_by.through.objects.filter(
            savedvisualization_id=OuterRef('pk'), user_id=user.id,
        )
        shared = Q(shared=True, entity_id=user.entity_id) if user.entity_id else Q(pk__in=[])
        qs = (
            SavedVisualization.objects
            .filter(Q(created_by=user) | shared)
            .select_related('created_by')
            .annotate(is_pinned=Exists(pinned))
        )
        params = self.request.query_params
        if params.get('pinned') == 'true':
            qs = qs.filter(is_pinned=True)
        if search := params.get('search', '').strip():
            qs = qs.filter(name__icontains=search)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, entity_id=self.request.user.entity_id)

    def perform_update(self, serializer):
        viz = serializer.save()
        if not viz.shared:
            # Unsharing takes it off everyone else's dashboard too.
            viz.pinned_by.remove(*viz.pinned_by.exclude(pk=viz.created_by_id))

    @action(detail=True, methods=['post', 'delete'], url_path='pin')
    def pin(self, request, pk=None):
        # Pinning only touches the caller's own dashboard, so anyone who can
        # see the visualization may pin it: no creator-only object check.
        viz = get_object_or_404(self.get_queryset(), pk=pk)
        if request.method == 'POST':
            viz.pinned_by.add(request.user)
        else:
            viz.pinned_by.remove(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
