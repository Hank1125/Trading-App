from django.contrib import admin
from django.urls import include, path

from clashroyale import views as cr_views
from markets import views as markets_views

urlpatterns = [
    path('', markets_views.dashboard, name='home'),
    path('clash/prices/', cr_views.prices, name='cr_prices'),
    path('markets/', include('markets.urls')),
    path('admin/', admin.site.urls),
]
