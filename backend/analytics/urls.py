from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('visualizations', views.SavedVisualizationViewSet, basename='analytics-visualization')

urlpatterns = [
    path('dimensions/', views.DimensionsView.as_view()),
    path('query/', views.AnalyticsQueryView.as_view()),
    path('items/', views.DimensionItemsView.as_view()),
] + router.urls
