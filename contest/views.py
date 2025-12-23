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
    ContestStatistics
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
