"""
URL configuration for Atrévete Admin
"""
from django.contrib import admin
from django.urls import path

from admin.core.views import status_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('admin/status/', status_view, name='admin_status'),
]
