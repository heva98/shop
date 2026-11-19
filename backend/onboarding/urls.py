from django.urls import path

from . import views

# Mounted under /api/catalog/ (config/urls.py): the paths the app uses.
urlpatterns = [
    path('quick-add/', views.quick_add),
    path('getting-started/', views.getting_started),
]
