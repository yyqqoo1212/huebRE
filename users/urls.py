from django.urls import path

from . import views

urlpatterns = [
    # 用户相关API
    path('register', views.register, name='user-register'),
    path('login', views.login, name='user-login'),
]

