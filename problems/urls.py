# -*- coding: utf-8 -*-

from django.urls import path

from . import views


urlpatterns = [

    # 创建题目（详细信息 + 简要信息）
    path('create', views.create_problem, name='problem-create'),
    
    # 获取题目列表（支持分页、搜索、筛选）
    path('list', views.list_problems, name='problem-list'),
    
    # 获取题目详情
    path('<int:problem_id>', views.get_problem_detail, name='problem-detail'),
]


