from django.contrib import admin
from django.urls import path

from clashroyale import views as cr_views

urlpatterns = [
    path('', cr_views.prices, name='cr_prices'),
    path('admin/', admin.site.urls),
]
