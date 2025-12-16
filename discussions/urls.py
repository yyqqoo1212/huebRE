from django.urls import path

from . import views

urlpatterns = [
    path('list', views.list_discussions, name='discussion-list'),
    path('create', views.create_discussion, name='discussion-create'),
    path('<int:discussion_id>', views.get_discussion_detail, name='discussion-detail'),
    path('<int:discussion_id>/update', views.update_discussion, name='discussion-update'),
    path('<int:discussion_id>/delete', views.delete_discussion, name='discussion-delete'),
]


