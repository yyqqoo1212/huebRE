# -*- coding: utf-8 -*-

from django.urls import path

from . import views


urlpatterns = [
    # 获取比赛列表
    path('list', views.list_contests, name='contest-list'),
    
    # 创建比赛
    path('create', views.create_contest, name='contest-create'),
    
    # 更新比赛
    path('update/<int:contest_id>', views.update_contest, name='contest-update'),
    
    # 删除比赛
    path('delete/<int:contest_id>', views.delete_contest, name='contest-delete'),
    
    # 比赛公告相关（需要放在比赛详情之前，因为路径更具体）
    path('<int:contest_id>/announcements/create', views.create_contest_announcement, name='contest-announcement-create'),
    path('<int:contest_id>/announcements/<int:announcement_id>/update', views.update_contest_announcement, name='contest-announcement-update'),
    path('<int:contest_id>/announcements/<int:announcement_id>/delete', views.delete_contest_announcement, name='contest-announcement-delete'),
    path('<int:contest_id>/announcements/<int:announcement_id>', views.get_contest_announcement_detail, name='contest-announcement-detail'),
    path('<int:contest_id>/announcements', views.get_contest_announcements, name='contest-announcements'),
    
    # 获取比赛详情（放在最后，作为兜底）
    path('<int:contest_id>', views.get_contest_detail, name='contest-detail'),
]

