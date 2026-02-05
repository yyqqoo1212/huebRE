# -*- coding: utf-8 -*-

from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    Contest,
    ContestTimeConfig,
    ContestRuleConfig,
    ContestPermissionConfig,
    ContestStatistics,
    ContestAnnouncement,
    ContestProblem,
    ContestRegistration
)
from users.views import _json_error, _json_success, _parse_request_body, jwt_required


def _get_dynamic_status(time_config: ContestTimeConfig) -> str:
    """
    根据当前时间动态计算比赛状态，并在需要时更新数据库中的状态字段。
    """
    if not time_config or not time_config.start_time or not time_config.end_time:
        return ContestTimeConfig.STATUS_UPCOMING

    start_time = time_config.start_time
    end_time = time_config.end_time

    # 确保时间为带时区的 aware datetime，避免比较错误
    current_tz = timezone.get_current_timezone()
    if timezone.is_naive(start_time):
        start_time = timezone.make_aware(start_time, current_tz)
    if timezone.is_naive(end_time):
        end_time = timezone.make_aware(end_time, current_tz)

    now = timezone.now()
    if now < start_time:
        status = ContestTimeConfig.STATUS_UPCOMING
    elif now <= end_time:
        status = ContestTimeConfig.STATUS_ACTIVE
    else:
        status = ContestTimeConfig.STATUS_ENDED

    # 如有变化，回写数据库（轻量级更新）
    if time_config.status != status:
        time_config.status = status
        time_config.save(update_fields=['status'])

    return status


@csrf_exempt
@jwt_required
@require_http_methods(['GET'])
def list_contest_submissions(request, contest_id):
    """
    获取某场比赛中题目的提交记录（支持分页、筛选）

    GET /api/contests/<contest_id>/submissions

    查询参数：
    - page: 页码（默认1）
    - page_size: 每页数量（默认20）
    - problem_id: 题库题目ID筛选（可选，Problem.problem_id）
    - user_id: 用户ID筛选（可选）
    - status: 状态筛选（可选，0=Accepted, -1=Wrong Answer, 1=Time Limit Exceeded, etc.）
    - language: 语言筛选（可选，cpp, java, python, javascript）
    """
    from problems.models import Submission

    try:
        contest_id = int(contest_id)
    except (TypeError, ValueError):
        return _json_error('比赛ID格式错误', status=400)

    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)

    # 获取本场比赛关联的题目集合
    contest_problems = ContestProblem.objects.filter(contest=contest).select_related('problem')
    problem_ids = [cp.problem_id for cp in contest_problems]

    # 如果比赛中没有题目，直接返回空结果
    if not problem_ids:
        return _json_success('获取成功', data={
            'submissions': [],
            'pagination': {
                'page': 1,
                'page_size': int(request.GET.get('page_size', '20') or 20),
                'total': 0,
                'total_pages': 0,
                'has_next': False,
                'has_previous': False,
            }
        })

    # 解析分页与筛选参数
    raw_page = request.GET.get('page', '1')
    raw_page_size = request.GET.get('page_size', '20')
    problem_id = request.GET.get('problem_id')
    user_id = request.GET.get('user_id')
    submission_id = request.GET.get('submission_id')
    status = request.GET.get('status')
    language = request.GET.get('language')

    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(raw_page_size)
    except (TypeError, ValueError):
        page_size = 20

    # 限制每页数量
    if page_size > 100:
        page_size = 100
    if page_size < 1:
        page_size = 20

    # 构建查询：限定为本比赛中的题目
    queryset = Submission.objects.select_related('problem', 'user').filter(
        problem_id__in=problem_ids
    )

    # 题目ID进一步筛选（题库 problem_id）
    if problem_id:
        try:
            problem_id = int(problem_id)
            queryset = queryset.filter(problem__problem_id=problem_id)
        except (TypeError, ValueError):
            pass

    # 测评ID筛选
    if submission_id:
        try:
            submission_id = int(submission_id)
            queryset = queryset.filter(submission_id=submission_id)
        except (TypeError, ValueError):
            pass

    # 用户ID筛选
    if user_id:
        try:
            user_id = int(user_id)
            queryset = queryset.filter(user_id=user_id)
        except (TypeError, ValueError):
            pass

    # 状态筛选
    if status is not None:
        try:
            status = int(status)
            queryset = queryset.filter(status=status)
        except (TypeError, ValueError):
            pass

    # 语言筛选
    if language:
        queryset = queryset.filter(language=language)

    # 按提交时间倒序排列
    queryset = queryset.order_by('-submit_time')

    # 分页
    paginator = Paginator(queryset, page_size)
    total = paginator.count
    total_pages = paginator.num_pages if total > 0 else 0

    try:
        submissions_page = paginator.page(page)
    except Exception:
        submissions_page = paginator.page(1)
        page = 1

    # 序列化提交记录
    submissions_data = []
    for s in submissions_page:
        submissions_data.append({
            'submission_id': s.submission_id,
            'problem_id': s.problem.problem_id,
            'problem_title': s.problem.title,
            'user_id': s.user.id,
            'username': s.user.username,
            'language': s.language,
            'status': s.status,
            'status_text': s.get_status_display(),
            'cpu_time': s.cpu_time,
            'memory': s.memory,
            'code_length': s.code_length,
            'submit_time': s.submit_time.isoformat(),
        })

    return _json_success('获取成功', data={
        'submissions': submissions_data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': total_pages,
            'has_next': submissions_page.has_next() if total > 0 else False,
            'has_previous': submissions_page.has_previous() if total > 0 else False,
        }
    })


@csrf_exempt
@require_http_methods(['GET'])
def list_contests(request):
    """
    获取比赛列表（支持分页、搜索、筛选）
    
    GET /api/contests/list
    
    查询参数：
    - page: 页码（默认1）
    - page_size: 每页数量（默认20）
    - search: 搜索关键词（比赛号或名称）
    - format: 赛制筛选（ACM/IOI/OI）
    - type: 赛种筛选（公开赛/私有赛）
    - status: 状态筛选（即将开始/进行中/已结束）
    """
    # 解析分页与筛选参数
    raw_page = request.GET.get('page', '1')
    raw_page_size = request.GET.get('page_size', '20')
    search = (request.GET.get('search', '') or '').strip()
    format_filter = request.GET.get('format')
    type_filter = request.GET.get('type')
    status_filter = request.GET.get('status')

    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(raw_page_size)
    except (TypeError, ValueError):
        page_size = 20
    
    # 限制每页数量
    if page_size > 100:
        page_size = 100
    if page_size < 1:
        page_size = 20
    
    # 构建查询
    queryset = Contest.objects.select_related(
        'time_config', 'rule_config', 'permission_config', 'statistics'
    ).filter(permission_config__visibility=True)
    
    # 搜索筛选（比赛号或名称）
    if search:
        try:
            contest_id = int(search)
            queryset = queryset.filter(contest_id=contest_id)
        except (TypeError, ValueError):
            queryset = queryset.filter(contest_name__icontains=search)
    
    # 赛制筛选
    if format_filter:
        queryset = queryset.filter(rule_config__contest_type=format_filter)
    
    # 赛种筛选
    if type_filter:
        queryset = queryset.filter(rule_config__contest_mode=type_filter)
    
    # 状态筛选
    if status_filter:
        queryset = queryset.filter(time_config__status=status_filter)
    
    # 按开始时间排序，越晚开始的排在前面
    queryset = queryset.order_by('-time_config__start_time')
    
    # 分页
    paginator = Paginator(queryset, page_size)
    
    try:
        page_obj = paginator.page(page)
    except Exception:
        return _json_error('页码超出范围', status=400)
    
    # 构建返回数据
    contests = []
    for contest in page_obj.object_list:
        time_config = getattr(contest, 'time_config', None)
        rule_config = getattr(contest, 'rule_config', None)
        statistics = getattr(contest, 'statistics', None)

        # 动态计算当前状态
        current_status = _get_dynamic_status(time_config) if time_config else ContestTimeConfig.STATUS_UPCOMING

        contests.append({
            'id': contest.contest_id,
            'name': contest.contest_name,
            'startTime': time_config.start_time.isoformat() if time_config else None,
            'duration': time_config.duration if time_config else 0,
            'format': rule_config.contest_type if rule_config else 'ACM',
            'type': rule_config.contest_mode if rule_config else '公开赛',
            'participants': statistics.participant_count if statistics else 0,
            'status': current_status,
        })
    
    return _json_success(
        '获取比赛列表成功',
        data={
            'contests': contests,
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
def get_contest_detail(request, contest_id):
    """
    获取比赛详情
    
    GET /api/contests/{contest_id}
    """
    try:
        contest_id = int(contest_id)
    except (TypeError, ValueError):
        return _json_error('比赛ID格式错误', status=400)
    
    try:
        contest = Contest.objects.select_related(
            'time_config', 'rule_config', 'permission_config', 'statistics'
        ).get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    time_config = getattr(contest, 'time_config', None)
    rule_config = getattr(contest, 'rule_config', None)
    permission_config = getattr(contest, 'permission_config', None)
    statistics = getattr(contest, 'statistics', None)

    # 动态计算并更新比赛状态
    current_status = _get_dynamic_status(time_config) if time_config else ContestTimeConfig.STATUS_UPCOMING
    
    return _json_success(
        '获取比赛详情成功',
        data={
            'id': contest.contest_id,
            'name': contest.contest_name,
            'description': contest.description or '',
            'creator_id': contest.creator_id,
            'create_time': contest.create_time.isoformat() if contest.create_time else None,
            'time_config': {
                'start_time': time_config.start_time.isoformat() if time_config else None,
                'end_time': time_config.end_time.isoformat() if time_config else None,
                'duration': time_config.duration if time_config else 0,
                'register_start_time': time_config.register_start_time.isoformat() if time_config and time_config.register_start_time else None,
                'register_end_time': time_config.register_end_time.isoformat() if time_config and time_config.register_end_time else None,
                'status': current_status,
            } if time_config else None,
            'rule_config': {
                'contest_type': rule_config.contest_type if rule_config else 'ACM',
                'contest_mode': rule_config.contest_mode if rule_config else '公开赛',
                'penalty_time': rule_config.penalty_time if rule_config else 20,
                'language_limit': rule_config.language_limit if rule_config else None,
                'allow_submit_after_end': rule_config.allow_submit_after_end if rule_config else False,
            } if rule_config else None,
            'permission_config': {
                'visibility': permission_config.visibility if permission_config else True,
                'show_rank': permission_config.show_rank if permission_config else True,
                'show_others_code': permission_config.show_others_code if permission_config else False,
                'show_testcase': permission_config.show_testcase if permission_config else False,
            } if permission_config else None,
            'statistics': {
                'participant_count': statistics.participant_count if statistics else 0,
                'registration_count': statistics.registration_count if statistics else 0,
                'submission_count': statistics.submission_count if statistics else 0,
                'problem_count': statistics.problem_count if statistics else 0,
                'ac_submission_count': statistics.ac_submission_count if statistics else 0,
            } if statistics else None,
        }
    )


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def create_contest(request):
    """
    创建比赛
    
    POST /api/contests/create
    
    请求体（JSON）示例：
    {
        "contest_name": "2024春季ACM程序设计竞赛",
        "description": "比赛描述",
        "start_time": "2024-03-20T09:00:00",
        "end_time": "2024-03-20T12:00:00",
        "duration": 180,
        "contest_type": "ACM",
        "contest_mode": "公开赛",
        "penalty_time": 20,
        "language_limit": ["cpp", "java", "python"],
        "allow_submit_after_end": false,
        "visibility": true,
        "show_rank": true,
        "show_others_code": false,
        "show_testcase": false
    }
    """
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')
    
    contest_name = (data.get('contest_name') or '').strip()
    if not contest_name:
        return _json_error('比赛名称不能为空', status=400)
    
    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)
    
    # 解析时间配置
    from django.utils.dateparse import parse_datetime
    from django.utils import timezone
    start_time_str = data.get('start_time')
    end_time_str = data.get('end_time')
    
    if not start_time_str or not end_time_str:
        return _json_error('开始时间和结束时间不能为空', status=400)
    
    start_time = parse_datetime(start_time_str)
    end_time = parse_datetime(end_time_str)
    
    if not start_time or not end_time:
        return _json_error('时间格式错误，请使用ISO格式', status=400)
    
    # 统一转换为带时区的时间，避免 naive / aware 比较错误
    current_tz = timezone.get_current_timezone()
    if timezone.is_naive(start_time):
        start_time = timezone.make_aware(start_time, current_tz)
    if timezone.is_naive(end_time):
        end_time = timezone.make_aware(end_time, current_tz)
    
    if start_time >= end_time:
        return _json_error('开始时间必须早于结束时间', status=400)
    
    try:
        duration = int(data.get('duration', 0))
    except (TypeError, ValueError):
        return _json_error('持续时间必须是整数（分钟）', status=400)
    
    # 解析规则配置
    contest_type = data.get('contest_type', 'ACM')
    if contest_type not in [ContestRuleConfig.CONTEST_TYPE_ACM, ContestRuleConfig.CONTEST_TYPE_IOI, ContestRuleConfig.CONTEST_TYPE_OI]:
        return _json_error('赛制类型错误', status=400)
    
    contest_mode = data.get('contest_mode', '公开赛')
    if contest_mode not in [ContestRuleConfig.CONTEST_MODE_PUBLIC, ContestRuleConfig.CONTEST_MODE_PRIVATE]:
        return _json_error('赛种类型错误', status=400)
    
    try:
        penalty_time = int(data.get('penalty_time', 20))
    except (TypeError, ValueError):
        penalty_time = 20
    
    language_limit = data.get('language_limit')
    allow_submit_after_end = data.get('allow_submit_after_end', False)
    
    # 解析权限配置
    visibility = data.get('visibility', True)
    show_rank = data.get('show_rank', True)
    show_others_code = data.get('show_others_code', False)
    show_testcase = data.get('show_testcase', False)
    
    # 计算状态
    now = timezone.now()
    if now < start_time:
        status = ContestTimeConfig.STATUS_UPCOMING
    elif now >= start_time and now <= end_time:
        status = ContestTimeConfig.STATUS_ACTIVE
    else:
        status = ContestTimeConfig.STATUS_ENDED
    
    # 创建比赛及相关配置
    try:
        with transaction.atomic():
            # 创建比赛基础信息
            contest = Contest.objects.create(
                contest_name=contest_name,
                description=data.get('description', ''),
                creator_id=user.id,
            )
            
            # 创建时间配置
            ContestTimeConfig.objects.create(
                contest=contest,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                register_start_time=parse_datetime(data.get('register_start_time')) if data.get('register_start_time') else None,
                register_end_time=parse_datetime(data.get('register_end_time')) if data.get('register_end_time') else None,
                status=status,
            )
            
            # 创建规则配置
            ContestRuleConfig.objects.create(
                contest=contest,
                contest_type=contest_type,
                contest_mode=contest_mode,
                password=data.get('password'),
                penalty_time=penalty_time,
                language_limit=language_limit,
                allow_submit_after_end=allow_submit_after_end,
            )
            
            # 创建权限配置
            ContestPermissionConfig.objects.create(
                contest=contest,
                visibility=visibility,
                show_rank=show_rank,
                show_others_code=show_others_code,
                show_testcase=show_testcase,
            )
            
            # 创建统计信息
            ContestStatistics.objects.create(
                contest=contest,
            )
    except Exception as exc:
        return _json_error(f'创建比赛失败: {str(exc)}', status=500, code='db_error')
    
    return _json_success(
        '创建比赛成功',
        data={
            'contest_id': contest.contest_id,
            'contest_name': contest.contest_name,
        },
        status=201,
    )


@csrf_exempt
@jwt_required
@require_http_methods(['PUT'])
def update_contest(request, contest_id):
    """
    更新比赛
    
    PUT /api/contests/update/<contest_id>
    """
    try:
        contest_id = int(contest_id)
    except (TypeError, ValueError):
        return _json_error('比赛ID格式错误', status=400)

    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    contest_name = (data.get('contest_name') or '').strip()
    if not contest_name:
        return _json_error('比赛名称不能为空', status=400)

    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)

    try:
        contest = Contest.objects.select_related(
            'time_config', 'rule_config', 'permission_config'
        ).get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)

    start_time_str = data.get('start_time')
    end_time_str = data.get('end_time')
    if not start_time_str or not end_time_str:
        return _json_error('开始时间和结束时间不能为空', status=400)

    start_time = parse_datetime(start_time_str)
    end_time = parse_datetime(end_time_str)

    if not start_time or not end_time:
        return _json_error('时间格式错误，请使用ISO格式', status=400)

    current_tz = timezone.get_current_timezone()
    if timezone.is_naive(start_time):
        start_time = timezone.make_aware(start_time, current_tz)
    if timezone.is_naive(end_time):
        end_time = timezone.make_aware(end_time, current_tz)

    if start_time >= end_time:
        return _json_error('开始时间必须早于结束时间', status=400)

    try:
        duration = int(data.get('duration', 0))
    except (TypeError, ValueError):
        return _json_error('持续时间必须是整数（分钟）', status=400)

    contest_type = data.get('contest_type', 'ACM')
    if contest_type not in [
        ContestRuleConfig.CONTEST_TYPE_ACM,
        ContestRuleConfig.CONTEST_TYPE_IOI,
        ContestRuleConfig.CONTEST_TYPE_OI,
    ]:
        return _json_error('赛制类型错误', status=400)

    contest_mode = data.get('contest_mode', '公开赛')
    if contest_mode not in [
        ContestRuleConfig.CONTEST_MODE_PUBLIC,
        ContestRuleConfig.CONTEST_MODE_PRIVATE,
    ]:
        return _json_error('赛种类型错误', status=400)

    try:
        penalty_time = int(data.get('penalty_time', 20))
    except (TypeError, ValueError):
        penalty_time = 20

    language_limit = data.get('language_limit')
    allow_submit_after_end = data.get('allow_submit_after_end', False)

    visibility = data.get('visibility', True)
    show_rank = data.get('show_rank', True)
    show_others_code = data.get('show_others_code', False)
    show_testcase = data.get('show_testcase', False)

    # 计算状态
    now = timezone.now()
    if now < start_time:
        status = ContestTimeConfig.STATUS_UPCOMING
    elif now >= start_time and now <= end_time:
        status = ContestTimeConfig.STATUS_ACTIVE
    else:
        status = ContestTimeConfig.STATUS_ENDED

    register_start_time = (
        parse_datetime(data.get('register_start_time')) if data.get('register_start_time') else None
    )
    register_end_time = (
        parse_datetime(data.get('register_end_time')) if data.get('register_end_time') else None
    )

    if register_start_time and register_end_time and register_end_time < register_start_time:
        return _json_error('报名结束时间不能早于报名开始时间', status=400)

    try:
        with transaction.atomic():
            contest.contest_name = contest_name
            contest.description = data.get('description', '')
            contest.save(update_fields=['contest_name', 'description', 'update_time'])

            # 时间配置
            time_config, _ = ContestTimeConfig.objects.select_for_update().get_or_create(
                contest=contest,
                defaults={
                    'start_time': start_time,
                    'end_time': end_time,
                    'duration': duration,
                    'register_start_time': register_start_time,
                    'register_end_time': register_end_time,
                    'status': status,
                }
            )
            time_config.start_time = start_time
            time_config.end_time = end_time
            time_config.duration = duration
            time_config.register_start_time = register_start_time
            time_config.register_end_time = register_end_time
            time_config.status = status
            time_config.save()

            # 规则配置
            rule_config, _ = ContestRuleConfig.objects.select_for_update().get_or_create(
                contest=contest
            )
            rule_config.contest_type = contest_type
            rule_config.contest_mode = contest_mode
            rule_config.password = data.get('password')
            rule_config.penalty_time = penalty_time
            rule_config.language_limit = language_limit
            rule_config.allow_submit_after_end = allow_submit_after_end
            rule_config.save()

            # 权限配置
            permission_config, _ = ContestPermissionConfig.objects.select_for_update().get_or_create(
                contest=contest
            )
            permission_config.visibility = visibility
            permission_config.show_rank = show_rank
            permission_config.show_others_code = show_others_code
            permission_config.show_testcase = show_testcase
            permission_config.save()

    except Exception as exc:
        return _json_error(f'更新比赛失败: {str(exc)}', status=500, code='db_error')

    return _json_success(
        '更新比赛成功',
        data={
            'contest_id': contest.contest_id,
            'contest_name': contest.contest_name,
        },
        status=200,
    )


@csrf_exempt
@jwt_required
@require_http_methods(['DELETE'])
def delete_contest(request, contest_id):
    """
    删除比赛
    
    DELETE /api/contests/delete/<contest_id>
    
    删除比赛及其所有相关数据：
    - Contest (主表)
    - ContestTimeConfig (自动级联删除)
    - ContestRuleConfig (自动级联删除)
    - ContestPermissionConfig (自动级联删除)
    - ContestStatistics (自动级联删除)
    
    预留接口：如果以后有其他需要手动删除的关联数据，可以在 _delete_contest_related_data 函数中添加
    """
    try:
        contest_id = int(contest_id)
    except (TypeError, ValueError):
        return _json_error('比赛ID格式错误', status=400)
    
    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)
    
    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    # 保存比赛名称用于返回信息
    contest_name = contest.contest_name
    
    try:
        with transaction.atomic():
            # 删除相关数据（预留扩展接口）
            # 当前由于使用了 CASCADE，删除 Contest 时会自动删除所有关联表
            # 如果以后有其他需要手动删除的数据（如文件、缓存等），可以在这里添加
            _delete_contest_related_data(contest)
            
            # 删除比赛主表（会自动级联删除所有关联表）
            contest.delete()
            
    except Exception as exc:
        return _json_error(f'删除比赛失败: {str(exc)}', status=500, code='db_error')
    
    return _json_success(
        '删除比赛成功',
        data={
            'contest_id': contest_id,
            'contest_name': contest_name,
        },
        status=200,
    )


def _delete_contest_related_data(contest: Contest):
    """
    删除比赛相关数据（预留扩展接口）
    
    当前所有关联表都使用了 CASCADE 删除，删除 Contest 时会自动删除。
    如果以后有以下情况需要手动删除，可以在此函数中添加：
    - 文件资源（如比赛图片、附件等）
    - 缓存数据
    - 其他非数据库关联的数据
    - 消息队列任务
    
    参数:
        contest: Contest 实例
    """
    # TODO: 如果以后有其他需要手动删除的数据，可以在这里添加
    # 例如：
    # - 删除比赛相关的文件
    # - 清理缓存
    # - 取消相关的定时任务
    # - 删除比赛相关的消息队列任务
    pass


@csrf_exempt
@require_http_methods(['GET'])
def get_contest_announcements(request, contest_id):
    """
    获取比赛公告列表
    
    GET /api/contests/<contest_id>/announcements
    """
    try:
        contest_id = int(contest_id)
    except (TypeError, ValueError):
        return _json_error('比赛ID格式错误', status=400)
    
    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    # 获取该比赛的所有公告，按重要性和时间排序
    announcements = ContestAnnouncement.objects.filter(contest=contest).order_by('-is_important', '-create_time')
    
    # 获取所有发布人ID，批量查询用户信息
    publisher_ids = [ann.publisher_id for ann in announcements if ann.publisher_id]
    from users.models import User
    publishers = {user.id: user.username for user in User.objects.filter(id__in=publisher_ids)} if publisher_ids else {}
    
    announcements_list = []
    for ann in announcements:
        announcements_list.append({
            'id': ann.id,
            'title': ann.title,
            'content': ann.content,
            'is_important': ann.is_important,
            'publisher_id': ann.publisher_id,
            'publisher_name': publishers.get(ann.publisher_id, '系统'),
            'create_time': ann.create_time.isoformat() if ann.create_time else None,
            'update_time': ann.update_time.isoformat() if ann.update_time else None,
        })
    
    return _json_success(
        '获取比赛公告列表成功',
        data={
            'announcements': announcements_list
        }
    )


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def create_contest_announcement(request, contest_id):
    """
    创建比赛公告
    
    POST /api/contests/<contest_id>/announcements
    
    请求体（JSON）：
    {
        "title": "公告标题",
        "content": "公告内容",
        "is_important": false
    }
    """
    try:
        contest_id = int(contest_id)
    except (TypeError, ValueError):
        return _json_error('比赛ID格式错误', status=400)
    
    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)
    
    # 检查用户权限：permission为1（管理员）或2（超级管理员）
    user_permission = getattr(user, 'permission', 0)
    try:
        user_permission = int(user_permission)
    except (TypeError, ValueError):
        user_permission = 0
    
    if user_permission not in [1, 2]:
        return _json_error('权限不足，需要管理员权限', status=403)
    
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')
    
    title = (data.get('title') or '').strip()
    if not title:
        return _json_error('公告标题不能为空', status=400)
    
    content = (data.get('content') or '').strip()
    if not content:
        return _json_error('公告内容不能为空', status=400)
    
    is_important = data.get('is_important', False)
    
    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    try:
        announcement = ContestAnnouncement.objects.create(
            contest=contest,
            title=title,
            content=content,
            is_important=is_important,
            publisher_id=user.id,
        )
    except Exception as exc:
        return _json_error(f'创建公告失败: {str(exc)}', status=500, code='db_error')
    
    return _json_success(
        '创建公告成功',
        data={
            'id': announcement.id,
            'title': announcement.title,
            'content': announcement.content,
            'is_important': announcement.is_important,
            'publisher_id': announcement.publisher_id,
            'publisher_name': user.username,
            'create_time': announcement.create_time.isoformat() if announcement.create_time else None,
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(['GET'])
def get_contest_announcement_detail(request, contest_id, announcement_id):
    """
    获取比赛公告详情
    
    GET /api/contests/<contest_id>/announcements/<announcement_id>
    """
    try:
        contest_id = int(contest_id)
        announcement_id = int(announcement_id)
    except (TypeError, ValueError):
        return _json_error('ID格式错误', status=400)
    
    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    try:
        announcement = ContestAnnouncement.objects.get(id=announcement_id, contest=contest)
    except ContestAnnouncement.DoesNotExist:
        return _json_error('公告不存在', status=404)
    
    # 获取发布人信息
    publisher_name = '系统'
    if announcement.publisher_id:
        try:
            from users.models import User
            publisher = User.objects.get(id=announcement.publisher_id)
            publisher_name = publisher.username
        except User.DoesNotExist:
            pass
    
    return _json_success(
        '获取公告详情成功',
        data={
            'id': announcement.id,
            'title': announcement.title,
            'content': announcement.content,
            'is_important': announcement.is_important,
            'publisher_id': announcement.publisher_id,
            'publisher_name': publisher_name,
            'create_time': announcement.create_time.isoformat() if announcement.create_time else None,
            'update_time': announcement.update_time.isoformat() if announcement.update_time else None,
        }
    )


@csrf_exempt
@jwt_required
@require_http_methods(['PUT'])
def update_contest_announcement(request, contest_id, announcement_id):
    """
    更新比赛公告（仅允许发布人编辑）
    
    PUT /api/contests/<contest_id>/announcements/<announcement_id>
    
    请求体（JSON）：
    {
        "title": "公告标题",
        "content": "公告内容",
        "is_important": false
    }
    """
    try:
        contest_id = int(contest_id)
        announcement_id = int(announcement_id)
    except (TypeError, ValueError):
        return _json_error('ID格式错误', status=400)
    
    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)
    
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')
    
    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    try:
        announcement = ContestAnnouncement.objects.get(id=announcement_id, contest=contest)
    except ContestAnnouncement.DoesNotExist:
        return _json_error('公告不存在', status=404)
    
    # 检查用户是否是公告的发布人
    if announcement.publisher_id != user.id:
        return _json_error('权限不足，只能编辑自己发布的公告', status=403)
    
    title = (data.get('title') or '').strip()
    if not title:
        return _json_error('公告标题不能为空', status=400)
    
    content = (data.get('content') or '').strip()
    if not content:
        return _json_error('公告内容不能为空', status=400)
    
    is_important = data.get('is_important', False)
    
    try:
        announcement.title = title
        announcement.content = content
        announcement.is_important = is_important
        announcement.save(update_fields=['title', 'content', 'is_important', 'update_time'])
    except Exception as exc:
        return _json_error(f'更新公告失败: {str(exc)}', status=500, code='db_error')
    
    return _json_success(
        '更新公告成功',
        data={
            'id': announcement.id,
            'title': announcement.title,
            'content': announcement.content,
            'is_important': announcement.is_important,
            'publisher_id': announcement.publisher_id,
            'publisher_name': user.username,
            'create_time': announcement.create_time.isoformat() if announcement.create_time else None,
            'update_time': announcement.update_time.isoformat() if announcement.update_time else None,
        },
        status=200,
    )


@csrf_exempt
@jwt_required
@require_http_methods(['DELETE'])
def delete_contest_announcement(request, contest_id, announcement_id):
    """
    删除比赛公告（仅允许发布人删除）
    
    DELETE /api/contests/<contest_id>/announcements/<announcement_id>
    """
    try:
        contest_id = int(contest_id)
        announcement_id = int(announcement_id)
    except (TypeError, ValueError):
        return _json_error('ID格式错误', status=400)
    
    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)
    
    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    try:
        announcement = ContestAnnouncement.objects.get(id=announcement_id, contest=contest)
    except ContestAnnouncement.DoesNotExist:
        return _json_error('公告不存在', status=404)
    
    # 检查用户权限：管理员（permission为1或2）可以删除任何公告，普通用户只能删除自己发布的公告
    user_permission = getattr(user, 'permission', 0)
    try:
        user_permission = int(user_permission)
    except (TypeError, ValueError):
        user_permission = 0
    
    # 如果不是管理员且不是发布人，则无权限
    if user_permission not in [1, 2] and announcement.publisher_id != user.id:
        return _json_error('权限不足，只能删除自己发布的公告', status=403)
    
    try:
        announcement_title = announcement.title
        announcement.delete()
    except Exception as exc:
        return _json_error(f'删除公告失败: {str(exc)}', status=500, code='db_error')
    
    return _json_success(
        '删除公告成功',
        data={
            'id': announcement_id,
            'title': announcement_title
        },
        status=200,
    )


@csrf_exempt
@require_http_methods(['GET'])
def get_contest_problems(request, contest_id):
    """
    获取比赛题目列表
    
    GET /api/contests/<contest_id>/problems
    """
    try:
        contest_id = int(contest_id)
    except (TypeError, ValueError):
        return _json_error('比赛ID格式错误', status=400)
    
    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    # 获取该比赛的所有题目，按display_order排序；select_related 避免 N+1
    problems = ContestProblem.objects.filter(contest=contest).select_related('problem').order_by('display_order')
    
    problems_list = []
    for problem in problems:
        problems_list.append({
            'id': problem.id,
            'problem_id': problem.problem.problem_id if problem.problem else None,
            'display_order': problem.display_order,
            'display_title': problem.display_title,
            'color': problem.color or '',
            'score': problem.score,
            'accept_count': problem.accept_count,
            'submit_count': problem.submit_count,
        })
    
    return _json_success(
        '获取比赛题目列表成功',
        data={
            'problems': problems_list
        }
    )


@csrf_exempt
@require_http_methods(['GET'])
def get_contest_problem_detail(request, contest_id, problem_id):
    """
    获取比赛题目详情（带比赛上下文，不校验题目 auth，用于比赛题目类型题目）

    GET /api/contests/<contest_id>/problems/<problem_id>
    problem_id 为题库题目 ID（Problem.problem_id）
    """
    from problems.models import Problem, ProblemData

    try:
        contest_id = int(contest_id)
        problem_id = int(problem_id)
    except (TypeError, ValueError):
        return _json_error('ID格式错误', status=400)

    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)

    try:
        contest_problem = ContestProblem.objects.select_related('problem', 'problem__stat').get(
            contest=contest, problem_id=problem_id
        )
    except ContestProblem.DoesNotExist:
        return _json_error('该题目不在本比赛中', status=404)

    problem = contest_problem.problem
    problem_data = problem.stat

    total_submissions = problem_data.submission
    pass_rate = (problem_data.ac / total_submissions * 100) if total_submissions > 0 else 0

    tags = []
    if problem_data.tag:
        tags = [t.strip() for t in problem_data.tag.split('|') if t.strip()]

    samples = []
    input_demo = problem.input_demo or ''
    output_demo = problem.output_demo or ''
    if input_demo or output_demo:
        input_list = input_demo.split('|') if input_demo else []
        input_list = [s.strip() for s in input_list if s.strip()]
        output_list = output_demo.split('|') if output_demo else []
        output_list = [s.strip() for s in output_list if s.strip()]
        max_len = max(len(input_list), len(output_list))
        for i in range(max_len):
            samples.append({
                'input': input_list[i] if i < len(input_list) else '',
                'output': output_list[i] if i < len(output_list) else ''
            })

    level_map = {
        ProblemData.LEVEL_EASY: 1,
        ProblemData.LEVEL_MEDIUM: 2,
        ProblemData.LEVEL_HARD: 3,
    }

    return _json_success(
        '获取题目详情成功',
        data={
            'id': problem.problem_id,
            'title': problem.title,
            'display_order': contest_problem.display_order or '',
            'display_title': contest_problem.display_title or problem.title,
            'content': problem.content,
            'input_description': problem.input_description,
            'output_description': problem.output_description,
            'input_demo': problem.input_demo,
            'output_demo': problem.output_demo,
            'samples': samples,
            'hint': problem.hint,
            'time_limit': problem.time_limit,
            'memory_limit': problem.memory_limit,
            'difficulty': level_map.get(problem_data.level, 1),
            'submissions': total_submissions,
            'accepted_count': problem_data.ac,
            'pass_rate': round(pass_rate, 1),
            'tags': tags,
            'score': problem_data.score,
            'auth': problem_data.auth,
            'author': problem.author,
            'create_time': timezone.localtime(problem.create_time).strftime('%Y-%m-%d %H:%M:%S') if problem.create_time else None,
        }
    )


@csrf_exempt
@require_http_methods(['GET'])
def get_problem_bank(request):
    """
    获取题库列表（用于比赛添加题目）
    
    GET /api/contests/problem-bank
    
    查询参数：
    - page: 页码（默认1）
    - page_size: 每页数量（默认10）
    - search: 搜索关键词（题号或标题）
    """
    from django.core.paginator import Paginator
    from problems.models import Problem, ProblemData
    
    # 解析分页与筛选参数
    raw_page = request.GET.get('page', '1')
    raw_page_size = request.GET.get('page_size', '10')
    search = (request.GET.get('search', '') or '').strip()

    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(raw_page_size)
    except (TypeError, ValueError):
        page_size = 10
    
    # 限制每页数量
    if page_size > 100:
        page_size = 100
    if page_size < 1:
        page_size = 10
    
    # 构建查询 - 获取公开题目
    queryset = ProblemData.objects.select_related('problem').filter(auth=Problem.PUBLIC)
    
    # 搜索筛选（题号或标题）
    if search:
        try:
            # 尝试将搜索词转换为整数（题号搜索）
            problem_id = int(search)
            queryset = queryset.filter(problem__problem_id=problem_id)
        except (TypeError, ValueError):
            # 标题搜索
            queryset = queryset.filter(title__icontains=search)
    
    # 按题号倒序排序
    queryset = queryset.order_by('-problem__problem_id')
    
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
        problems.append({
            'id': problem.problem_id,
            'title': problem_data.title,
        })
    
    return _json_success(
        '获取题库列表成功',
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
@jwt_required
@require_http_methods(['GET'])
def get_contest_registration(request, contest_id):
    """
    查询当前登录用户在指定比赛的报名信息

    GET /api/contests/<contest_id>/registration
    """
    try:
        contest_id = int(contest_id)
    except (TypeError, ValueError):
        return _json_error('比赛ID格式错误', status=400)

    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)

    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)

    registration = ContestRegistration.objects.filter(contest=contest, user=user).first()
    if not registration:
        return _json_success('未报名', data={'registered': False})

    return _json_success('已报名', data={
        'registered': True,
        'registration': {
            'id': registration.id,
            'contest_id': contest.contest_id,
            'user_id': user.id,
            'real_name': registration.real_name,
            'student_id': registration.student_id,
            'school': registration.school,
            'phone': registration.phone,
            'email': registration.email,
            'status': registration.status,
            'is_star': registration.is_star,
            'register_time': registration.register_time.isoformat() if registration.register_time else None,
        }
    })


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def register_for_contest(request, contest_id):
    """
    报名比赛（同一用户同一比赛只能报名一次）

    POST /api/contests/<contest_id>/registration

    请求体（JSON，可选字段）：
    {
        "real_name": "...",
        "student_id": "...",
        "school": "...",
        "phone": "...",
        "email": "...",
        "is_star": false
    }
    """
    try:
        contest_id = int(contest_id)
    except (TypeError, ValueError):
        return _json_error('比赛ID格式错误', status=400)

    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)

    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)

    # 已报名则直接返回成功，避免重复报错
    existing = ContestRegistration.objects.filter(contest=contest, user=user).first()
    if existing:
        return _json_success('已报名', data={
            'registered': True,
            'registration': {
                'id': existing.id,
                'contest_id': contest.contest_id,
                'user_id': user.id,
                'real_name': existing.real_name,
                'student_id': existing.student_id,
                'school': existing.school,
                'phone': existing.phone,
                'email': existing.email,
                'status': existing.status,
                'is_star': existing.is_star,
                'register_time': existing.register_time.isoformat() if existing.register_time else None,
            }
        })

    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    registration = ContestRegistration.objects.create(
        contest=contest,
        user=user,
        real_name=data.get('real_name') or None,
        student_id=data.get('student_id') or None,
        school=data.get('school') or None,
        phone=data.get('phone') or None,
        email=data.get('email') or None,
        is_star=bool(data.get('is_star', False)),
        status=ContestRegistration.STATUS_SUCCESS
    )

    return _json_success('报名成功', data={
        'registered': True,
        'registration': {
            'id': registration.id,
            'contest_id': contest.contest_id,
            'user_id': user.id,
            'real_name': registration.real_name,
            'student_id': registration.student_id,
            'school': registration.school,
            'phone': registration.phone,
            'email': registration.email,
            'status': registration.status,
            'is_star': registration.is_star,
            'register_time': registration.register_time.isoformat() if registration.register_time else None,
        }
    })


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def add_problem_to_contest(request, contest_id):
    """
    添加题目到比赛
    
    POST /api/contests/<contest_id>/problems/add
    
    请求体（JSON）：
    {
        "problem_id": 1,
        "display_title": "题目标题"  // 可选，不提供则使用题目原标题
    }
    """
    try:
        contest_id = int(contest_id)
    except (TypeError, ValueError):
        return _json_error('比赛ID格式错误', status=400)
    
    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)
    
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')
    
    problem_id = data.get('problem_id')
    if not problem_id:
        return _json_error('题目ID不能为空', status=400)
    
    try:
        problem_id = int(problem_id)
    except (TypeError, ValueError):
        return _json_error('题目ID格式错误', status=400)
    
    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    # 检查题目是否存在
    from problems.models import Problem, ProblemData
    try:
        problem = Problem.objects.get(problem_id=problem_id)
        problem_data = ProblemData.objects.get(problem=problem)
    except Problem.DoesNotExist:
        return _json_error('题目不存在', status=404)
    except ProblemData.DoesNotExist:
        return _json_error('题目数据不存在', status=404)
    
    # 检查题目是否已经在比赛中
    if ContestProblem.objects.filter(contest=contest, problem=problem).exists():
        return _json_error('该题目已在比赛中', status=400)
    
    try:
        with transaction.atomic():
            # 自动生成 display_order（按字母顺序：A, B, C...）
            existing_problems = ContestProblem.objects.filter(contest=contest).order_by('display_order')
            if existing_problems.exists():
                # 获取最后一个题目的序号
                last_order = existing_problems.last().display_order
                # 生成下一个序号
                if last_order.isalpha() and len(last_order) == 1:
                    # 如果是单个字母，生成下一个字母
                    next_char = chr(ord(last_order) + 1)
                    display_order = next_char
                else:
                    # 如果不是标准格式，使用数字
                    display_order = str(existing_problems.count() + 1)
            else:
                # 第一道题目，使用 A
                display_order = 'A'
            
            # 使用提供的标题或原标题
            display_title = data.get('display_title', '').strip()
            if not display_title:
                display_title = problem_data.title
            
            # 创建比赛题目关联
            contest_problem = ContestProblem.objects.create(
                contest=contest,
                problem=problem,
                display_order=display_order,
                display_title=display_title,
                score=100,  # IOI/OI赛制分数，默认为空
                color=None,  # ACM赛制气球颜色，默认为空
                accept_count=0,
                submit_count=0,
                first_blood_user_id=None,
                first_blood_time=None,
            )
            
            # 更新比赛统计信息
            statistics, created = ContestStatistics.objects.get_or_create(contest=contest)
            statistics.problem_count = ContestProblem.objects.filter(contest=contest).count()
            statistics.save()
            
    except Exception as exc:
        return _json_error(f'添加题目失败: {str(exc)}', status=500, code='db_error')
    
    return _json_success(
        '添加题目成功',
        data={
            'id': contest_problem.id,
            'problem_id': problem.problem_id,
            'display_order': contest_problem.display_order,
            'display_title': contest_problem.display_title,
        },
        status=201,
    )


@csrf_exempt
@jwt_required
@require_http_methods(['DELETE'])
def delete_contest_problem(request, contest_id, problem_relation_id):
    """
    删除比赛题目关联（不删除原题目）
    
    DELETE /api/contests/<contest_id>/problems/<problem_relation_id>/delete
    """
    try:
        contest_id = int(contest_id)
        problem_relation_id = int(problem_relation_id)
    except (TypeError, ValueError):
        return _json_error('ID格式错误', status=400)
    
    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)
    
    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    try:
        contest_problem = ContestProblem.objects.get(id=problem_relation_id, contest=contest)
    except ContestProblem.DoesNotExist:
        return _json_error('比赛题目关联不存在', status=404)
    
    try:
        with transaction.atomic():
            problem_title = contest_problem.display_title
            contest_problem.delete()
            
            # 更新比赛统计信息
            statistics, created = ContestStatistics.objects.get_or_create(contest=contest)
            statistics.problem_count = ContestProblem.objects.filter(contest=contest).count()
            statistics.save()
            
    except Exception as exc:
        return _json_error(f'删除题目失败: {str(exc)}', status=500, code='db_error')
    
    return _json_success(
        '删除题目成功',
        data={
            'id': problem_relation_id,
            'title': problem_title,
        },
        status=200,
    )


@csrf_exempt
@jwt_required
@require_http_methods(['PUT'])
def update_contest_problem_color(request, contest_id, problem_relation_id):
    """
    更新比赛题目气球颜色
    
    PUT /api/contests/<contest_id>/problems/<problem_relation_id>/color
    
    请求体（JSON）：
    {
        "color": "#FF0000"
    }
    """
    try:
        contest_id = int(contest_id)
        problem_relation_id = int(problem_relation_id)
    except (TypeError, ValueError):
        return _json_error('ID格式错误', status=400)
    
    user = request.user
    if not user:
        return _json_error('用户未登录', status=401)
    
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')
    
    color = data.get('color', '').strip()
    if not color:
        return _json_error('颜色值不能为空', status=400)
    
    try:
        contest = Contest.objects.get(contest_id=contest_id)
    except Contest.DoesNotExist:
        return _json_error('比赛不存在', status=404)
    
    try:
        contest_problem = ContestProblem.objects.get(id=problem_relation_id, contest=contest)
    except ContestProblem.DoesNotExist:
        return _json_error('比赛题目关联不存在', status=404)
    
    try:
        contest_problem.color = color
        contest_problem.save(update_fields=['color', 'update_time'])
    except Exception as exc:
        return _json_error(f'更新颜色失败: {str(exc)}', status=500, code='db_error')
    
    return _json_success(
        '更新颜色成功',
        data={
            'id': contest_problem.id,
            'color': contest_problem.color,
        },
        status=200,
    )