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

    # 删除题目
    path('<int:problem_id>/delete', views.delete_problem, name='problem-delete'),

    # 更新题目
    path('<int:problem_id>/update', views.update_problem, name='problem-update'),

    # 上传压缩包并解压验证
    path('upload-zip', views.upload_and_validate_zip, name='problem-upload-zip'),

    # 上传手动输入的测试用例
    path('<int:problem_id>/upload-testcases', views.upload_testcase_files, name='problem-upload-testcases'),

    # 上传解压后的测试用例
    path('<int:problem_id>/upload-extracted-testcases', views.upload_extracted_testcases, name='problem-upload-extracted'),

    # 清空题目测评数据
    path('<int:problem_id>/testcases/clear', views.clear_problem_testcases, name='problem-clear-testcases'),
    
    # 运行自测
    path('<int:problem_id>/run-test', views.run_test, name='problem-run-test'),
    
    # 提交代码进行判题（使用题目的时间限制和内存限制）
    path('<int:problem_id>/submit', views.submit_code, name='problem-submit'),
    
    # 通用判题接口（返回完整JSON结果）
    path('judge', views.judge, name='problem-judge'),
    
    # 获取提交列表
    path('submissions/list', views.list_submissions, name='submission-list'),
    
    # 获取提交详情
    path('submissions/<int:submission_id>', views.get_submission_detail, name='submission-detail'),
]


