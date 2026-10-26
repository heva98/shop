from django.urls import path

from . import finance, views

urlpatterns = [
    path('dashboard/', views.dashboard),
    path('sales/', views.sales),
    path('sales-trend/', views.sales_trend),
    path('shifts/', views.shifts),
    path('stock/', views.stock),
    path('expiry/', views.expiry),
    path('purchases/', views.purchases),
    path('losses/', views.losses),
    path('payables/', finance.payables),
    path('margin/', finance.margin),
    path('movers/', finance.movers),
    path('transfers/', finance.transfers),
]
