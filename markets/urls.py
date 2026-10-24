from django.urls import path

from markets import views

app_name = 'markets'
urlpatterns = [
    path('', views.market_list, name='list'),
    path('portfolio/', views.portfolio, name='portfolio'),
    path('wallet/', views.wallet, name='wallet'),
    path('<int:pk>/', views.market_detail, name='detail'),
    path('<int:pk>/quote/', views.quote, name='quote'),
    path('<int:pk>/trade/', views.trade, name='trade'),
]
