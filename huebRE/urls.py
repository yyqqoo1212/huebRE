# -*- coding: utf-8 -*-、

"""
URL configuration for huebRE project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from users import views as storage_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # 用户相关API
    path('api/users/', include('users.urls')),

    # 题目相关API
    path('api/problems/', include('problems.urls')),

    # 讨论区相关API
    path('api/discussions/', include('discussions.urls')),

    # 比赛相关API
    path('api/contests/', include('contest.urls')),

    # Minio文件存储相关API
    path('api/files/upload', storage_views.upload_file, name='file-upload'),
    path('api/files/upload-temp', storage_views.upload_temp_file, name='file-upload-temp'),
    path('api/files/get', storage_views.get_file, name='file-get'),
    path('api/files/download', storage_views.download_file, name='file-download'),
    path('api/files/delete', storage_views.delete_file, name='file-delete'),
    path('api/files/check', storage_views.check_file, name='file-check'),
]
