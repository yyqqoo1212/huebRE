# -*- coding: utf-8 -*-

from django.urls import path

from . import views


urlpatterns = [
    # 获取比赛列表
    path('list', views.list_contests, name='contest-list'),
    
    # 获取比赛详情
    path('<int:contest_id>', views.get_contest_detail, name='contest-detail'),
    
    # 创建比赛
    path('create', views.create_contest, name='contest-create'),

    # 更新比赛
    path('update/<int:contest_id>', views.update_contest, name='contest-update'),
]

