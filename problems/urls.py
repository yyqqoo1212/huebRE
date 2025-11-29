# -*- coding: utf-8 -*-

from django.urls import path

from . import views


urlpatterns = [
    # 模块健康检查
    path('health', views.health, name='problems-health'),

    # 创建题目（详细信息 + 简要信息）
    path('create', views.create_problem, name='problem-create'),
]


