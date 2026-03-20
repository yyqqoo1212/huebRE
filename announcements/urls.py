from django.urls import path

from . import views

urlpatterns = [
    # 公告列表（公开）
    path('list', views.list_announcements, name='announcement-list'),

    # 公告详情（公开）
    path('<int:announcement_id>', views.get_announcement_detail, name='announcement-detail'),

    # 公告增删改（管理员权限）
    path('create', views.create_announcement, name='announcement-create'),
    path('<int:announcement_id>/update', views.update_announcement, name='announcement-update'),
    path('<int:announcement_id>/delete', views.delete_announcement, name='announcement-delete'),
]

