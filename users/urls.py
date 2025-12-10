# -*- coding: utf-8 -*-


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
    
    # 管理员API（需要管理员权限）
    path('list', views.list_users, name='user-list'),
    path('<int:user_id>/delete', views.delete_user, name='user-delete'),
    path('<int:user_id>/update', views.update_user, name='user-update'),
    path('<int:user_id>/reset-password', views.reset_user_password, name='user-reset-password'),
]