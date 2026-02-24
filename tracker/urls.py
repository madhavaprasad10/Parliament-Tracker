from django.urls import path
from . import views

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('bills/', views.bill_list, name='bill_list'),
    path('bills/<uuid:pk>/', views.bill_detail, name='bill_detail'),
    path('analytics/', views.analytics, name='analytics'),
    path('map/', views.map_view, name='map'),
    path('calendar/', views.calendar_view, name='calendar'),
    path('api/bills/', views.api_bills, name='api_bills'),
    path('export/', views.export_bills, name='export_bills'),   # <-- this line
]