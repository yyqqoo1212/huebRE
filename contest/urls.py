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
    
    # 比赛题目相关
    path('<int:contest_id>/problems', views.get_contest_problems, name='contest-problems'),
    path('<int:contest_id>/problems/add', views.add_problem_to_contest, name='contest-add-problem'),
    path('<int:contest_id>/problems/<int:problem_id>', views.get_contest_problem_detail, name='contest-problem-detail'),
    path('<int:contest_id>/problems/<int:problem_relation_id>/delete', views.delete_contest_problem, name='contest-delete-problem'),
    path('<int:contest_id>/problems/<int:problem_relation_id>/color', views.update_contest_problem_color, name='contest-update-problem-color'),
    path('problem-bank', views.get_problem_bank, name='contest-problem-bank'),

    # 比赛报名
    path('<int:contest_id>/registration', views.get_contest_registration, name='contest-registration-get'),
    path('<int:contest_id>/registration/apply', views.register_for_contest, name='contest-registration-post'),

    # 比赛提交记录
    path('<int:contest_id>/submissions', views.list_contest_submissions, name='contest-submissions'),
    
    # 获取比赛详情（放在最后，作为兜底）
    path('<int:contest_id>', views.get_contest_detail, name='contest-detail'),
]

