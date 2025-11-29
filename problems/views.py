# -*- coding: utf-8 -*-

from django.db import IntegrityError, transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django.http import HttpResponse, JsonResponse

from problems.models import Problem, ProblemData
from users.views import _json_error, _json_success, _parse_request_body, jwt_required


@csrf_exempt
@require_http_methods(['GET'])
def list_problems(request):
    """
    获取题目列表（支持分页、搜索、难度筛选）
    
    GET /api/problems/list
    
    查询参数：
    - page: 页码（默认1）
    - page_size: 每页数量（默认20）
    - search: 搜索关键词（题号或标题）
    - level: 难度筛选（1=简单, 2=中等, 3=困难）
    - auth: 权限筛选（1=公开, 2=私密, 3=比赛）
    """
    from django.core.paginator import Paginator
    
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        search = request.GET.get('search', '').strip()
        level = request.GET.get('level')
        auth = request.GET.get('auth')
    except (TypeError, ValueError):
        return _json_error('参数格式错误', status=400)
    
    # 限制每页数量
    if page_size > 100:
        page_size = 100
    if page_size < 1:
        page_size = 20
    
    # 构建查询
    queryset = ProblemData.objects.select_related('problem').filter(auth=Problem.PUBLIC)
    
    # 难度筛选
    if level:
        try:
            level = int(level)
            if level in (ProblemData.LEVEL_EASY, ProblemData.LEVEL_MEDIUM, ProblemData.LEVEL_HARD):
                queryset = queryset.filter(level=level)
        except (TypeError, ValueError):
            pass
    
    # 权限筛选
    if auth:
        try:
            auth = int(auth)
            if auth in (Problem.PUBLIC, Problem.PRIVATE, Problem.CONTEST):
                queryset = queryset.filter(auth=auth)
        except (TypeError, ValueError):
            pass
    
    # 搜索筛选（题号或标题）
    if search:
        try:
            # 尝试将搜索词转换为整数（题号搜索）
            problem_id = int(search)
            queryset = queryset.filter(problem__problem_id=problem_id)
        except (TypeError, ValueError):
            # 标题搜索
            queryset = queryset.filter(title__icontains=search)
    
    # 按题号排序
    queryset = queryset.order_by('problem__problem_id')
    
    # 分页
    paginator = Paginator(queryset, page_size)
    
    try:
        page_obj = paginator.page(page)
    except Exception:
        return _json_error('页码超出范围', status=400)
    
    # 构建返回数据
    problems = []
    for problem_data in page_obj.object_list:
        problem = problem_data.problem
        # 计算通过率
        total_submissions = problem_data.submission
        pass_rate = (problem_data.ac / total_submissions * 100) if total_submissions > 0 else 0
        
        # 处理标签
        tags = []
        if problem_data.tag:
            tags = [tag.strip() for tag in problem_data.tag.split('|') if tag.strip()]
        
        # 难度映射
        level_map = {
            ProblemData.LEVEL_EASY: 'easy',
            ProblemData.LEVEL_MEDIUM: 'medium',
            ProblemData.LEVEL_HARD: 'hard'
        }
        
        problems.append({
            'id': problem.problem_id,
            'title': problem_data.title,
            'tags': tags,
            'difficulty': level_map.get(problem_data.level, 'easy'),
            'submissions': total_submissions,
            'passRate': round(pass_rate, 1),
            'ac': problem_data.ac,
            'score': problem_data.score,
        })
    
    return _json_success(
        '获取题目列表成功',
        data={
            'problems': problems,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': paginator.count,
                'total_pages': paginator.num_pages,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            }
        }
    )


@csrf_exempt
@require_http_methods(['GET'])
def get_problem_detail(request, problem_id):
    """
    获取题目详情
    
    GET /api/problems/{problem_id}
    """
    try:
        problem_id = int(problem_id)
    except (TypeError, ValueError):
        return _json_error('题目ID格式错误', status=400)
    
    try:
        # 获取题目详细信息
        problem = Problem.objects.select_related('stat').get(problem_id=problem_id, auth=Problem.PUBLIC)
        problem_data = problem.stat
    except Problem.DoesNotExist:
        return _json_error('题目不存在或无权限访问', status=404)
    except Exception as e:
        return _json_error(f'获取题目详情失败: {str(e)}', status=500)
    
    # 计算通过率
    total_submissions = problem_data.submission
    pass_rate = (problem_data.ac / total_submissions * 100) if total_submissions > 0 else 0
    
    # 处理标签
    tags = []
    if problem_data.tag:
        tags = [tag.strip() for tag in problem_data.tag.split('|') if tag.strip()]
    
    # 处理样例数据（支持多组，用 | 分隔）
    samples = []
    input_demo = problem.input_demo or ''
    output_demo = problem.output_demo or ''
    
    if input_demo or output_demo:
        # 分割输入样例
        input_list = input_demo.split('|') if input_demo else []
        input_list = [item.strip() for item in input_list if item.strip()]
        
        # 分割输出样例
        output_list = output_demo.split('|') if output_demo else []
        output_list = [item.strip() for item in output_list if item.strip()]
        
        # 确定样例组数（取输入和输出的最大长度）
        max_length = max(len(input_list), len(output_list))
        
        # 构建样例列表
        for i in range(max_length):
            samples.append({
                'input': input_list[i] if i < len(input_list) else '',
                'output': output_list[i] if i < len(output_list) else ''
            })
    
    # 难度映射
    level_map = {
        ProblemData.LEVEL_EASY: 1,
        ProblemData.LEVEL_MEDIUM: 2,
        ProblemData.LEVEL_HARD: 3
    }
    
    return _json_success(
        '获取题目详情成功',
        data={
            'id': problem.problem_id,
            'title': problem.title,
            'content': problem.content,
            'input_description': problem.input_description,
            'output_description': problem.output_description,
            'input_demo': problem.input_demo,  # 保留原始数据，兼容旧代码
            'output_demo': problem.output_demo,  # 保留原始数据，兼容旧代码
            'samples': samples,  # 新增：解析后的样例数组
            'hint': problem.hint,
            'time_limit': problem.time_limit,
            'memory_limit': problem.memory_limit,
            'difficulty': level_map.get(problem_data.level, 1),
            'submissions': total_submissions,
            'accepted_count': problem_data.ac,
            'pass_rate': round(pass_rate, 1),
            'tags': tags,
            'score': problem_data.score,
            'author': problem.author,
            'create_time': problem.create_time.strftime('%Y-%m-%d %H:%M:%S') if problem.create_time else None,
        }
    )


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
