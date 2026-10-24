from django.contrib import admin
from django.urls import include, path

from clashroyale import views as cr_views

urlpatterns = [
    path('', cr_views.prices, name='cr_prices'),
    path('markets/', include('markets.urls')),
    path('admin/', admin.site.urls),
]
