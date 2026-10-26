from django.urls import path

from . import views

urlpatterns = [
    path('', views.kinds),
    path('<slug:kind>/template/', views.template),
    path('<slug:kind>/', views.run_import),
]
