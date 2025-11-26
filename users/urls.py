from django.urls import path

from . import views

urlpatterns = [
    # 用户相关API
    path('register', views.register, name='user-register'),
    path('login', views.login, name='user-login'),
    
    # 用户设置相关API（需要认证）
    path('me', views.user_profile, name='user-profile'),
    path('change-password', views.change_password, name='user-change-password'),
    path('delete-account', views.delete_account, name='user-delete-account'),
]