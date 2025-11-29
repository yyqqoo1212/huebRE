# -*- coding: utf-8 -*-

from django.db import IntegrityError, transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django.http import HttpResponse, JsonResponse

from problems.models import Problem, ProblemData
from users.views import _json_error, _json_success, _parse_request_body, jwt_required


def health(request):
    """
    简单的健康检查视图，后续可替换为真实题目接口
    """
    return JsonResponse({'code': 'success', 'message': 'problems module ready'})


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def create_problem(request):
    """
    创建题目（详细信息 + 简要信息）

    POST /api/problems/create

    请求体（JSON）示例：
    {
        "author": "admin",
        "title": "两数之和",
        "content": "...",
        "input_description": "...",
        "output_description": "...",
        "input_demo": "1 2",
        "output_demo": "3",
        "time_limit": 1000,
        "memory_limit": 256,
        "hint": "",
        "auth": 1,
        "level": 1,
        "tag": "数组|模拟",
        "score": 100
    }
    """
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    title = (data.get('title') or '').strip()
    author = (data.get('author') or '').strip()

    if not title:
        return _json_error('标题不能为空', status=400)
    if not author:
        return _json_error('作者不能为空', status=400)

    # 详细信息字段
    content = data.get('content') or ''
    input_description = data.get('input_description') or ''
    output_description = data.get('output_description') or ''
    input_demo = data.get('input_demo') or ''
    output_demo = data.get('output_demo') or ''
    hint = data.get('hint') or ''

    try:
        time_limit = int(data.get('time_limit') or 1000)
    except (TypeError, ValueError):
        return _json_error('time_limit 必须是整数（毫秒）', status=400)

    try:
        memory_limit = int(data.get('memory_limit') or 256)
    except (TypeError, ValueError):
        return _json_error('memory_limit 必须是整数（MB）', status=400)

    try:
        auth = int(data.get('auth') or Problem.PUBLIC)
    except (TypeError, ValueError):
        auth = Problem.PUBLIC

    if auth not in (Problem.PUBLIC, Problem.PRIVATE, Problem.CONTEST):
        return _json_error('auth 非法，只能是 1/2/3', status=400)

    # 简要信息字段
    try:
        level = int(data.get('level') or ProblemData.LEVEL_EASY)
    except (TypeError, ValueError):
        level = ProblemData.LEVEL_EASY

    if level not in (ProblemData.LEVEL_EASY, ProblemData.LEVEL_MEDIUM, ProblemData.LEVEL_HARD):
        return _json_error('level 非法，只能是 1/2/3', status=400)

    tag = (data.get('tag') or '').strip()

    try:
        score = int(data.get('score') or 100)
    except (TypeError, ValueError):
        return _json_error('score 必须是整数', status=400)

    # 创建题目和统计信息
    try:
        with transaction.atomic():
            problem = Problem.objects.create(
                author=author,
                title=title,
                content=content,
                input_description=input_description,
                output_description=output_description,
                input_demo=input_demo,
                output_demo=output_demo,
                time_limit=time_limit,
                memory_limit=memory_limit,
                hint=hint,
                auth=auth,
            )

            ProblemData.objects.create(
                problem=problem,
                title=title,
                level=level,
                tag=tag,
                auth=auth,
                score=score,
            )
    except IntegrityError:
        return _json_error('创建题目失败，请重试', status=500, code='db_error')
    except Exception as exc:
        return _json_error(f'创建题目失败: {str(exc)}', status=500, code='db_error')

    return _json_success(
        '创建题目成功',
        data={
            'problem_id': problem.problem_id,
            'title': problem.title,
            'author': problem.author,
            'auth': problem.auth,
            'time_limit': problem.time_limit,
            'memory_limit': problem.memory_limit,
            'level': level,
            'tag': tag,
            'score': score,
        },
        status=201,
    )
