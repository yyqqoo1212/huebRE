from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Discussion
from users.models import User
from users.views import _json_error, _json_success, _parse_request_body, jwt_required


def _serialize_discussion(d: Discussion, include_content=False) -> dict:
    """序列化讨论信息，字段命名尽量贴合前端已有结构。"""
    result = {
        'id': d.id,
        'title': d.title,
        'type': d.type,
        'author': d.author.username if isinstance(d.author, User) else str(d.author),
        'author_id': d.author.id if isinstance(d.author, User) else None,
        'comments': d.comments_count,
        'likes': d.likes_count,
        'views': d.views_count,
        'is_pinned': d.is_pinned,
        'publishTime': d.created_at.isoformat() if d.created_at else None,
    }
    if include_content:
        result['content'] = d.content
    return result


@csrf_exempt
@require_http_methods(['GET'])
def list_discussions(request):
    """
    获取讨论列表

    GET /api/discussions/list

    查询参数：
    - page: 页码（默认1）
    - page_size: 每页数量（默认20，最大100）
    - type: 类型筛选（solution/chat/help/share）
    """
    raw_page = request.GET.get('page', '1')
    raw_page_size = request.GET.get('page_size', '20')
    type_filter = (request.GET.get('type') or '').strip()

    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(raw_page_size)
    except (TypeError, ValueError):
        page_size = 20

    if page_size < 1:
        page_size = 20
    if page_size > 100:
        page_size = 100

    queryset = Discussion.objects.select_related('author').all()

    if type_filter:
        queryset = queryset.filter(type=type_filter)

    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except Exception:
        return _json_error('页码超出范围', status=400)

    discussions_data = [_serialize_discussion(d, include_content=False) for d in page_obj.object_list]

    return _json_success(
        '获取讨论列表成功',
        data={
            'discussions': discussions_data,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': paginator.count,
                'total_pages': paginator.num_pages,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
        },
    )


@csrf_exempt
@require_http_methods(['GET'])
def get_discussion_detail(request, discussion_id):
    """
    获取讨论详情

    GET /api/discussions/<id>
    """
    try:
        discussion_id = int(discussion_id)
    except (TypeError, ValueError):
        return _json_error('讨论ID格式错误', status=400)

    try:
        discussion = Discussion.objects.select_related('author').get(id=discussion_id)
    except Discussion.DoesNotExist:
        return _json_error('讨论不存在', status=404)
    except Exception as exc:
        return _json_error(f'获取讨论详情失败: {str(exc)}', status=500)

    # 增加浏览量
    discussion.views_count += 1
    discussion.save(update_fields=['views_count'])

    data = _serialize_discussion(discussion, include_content=True)

    return _json_success('获取讨论详情成功', data=data)


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def create_discussion(request):
    """
    创建讨论

    POST /api/discussions/create

    请求体（JSON）：
    - title: 标题（必填）
    - type: 类型（solution/chat/help/share，必填）
    - content: Markdown 内容（必填）
    """
    user = request.user

    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    title = (data.get('title') or '').strip()
    type_value = (data.get('type') or '').strip() or Discussion.TYPE_CHAT
    content = (data.get('content') or '').strip()

    if not title:
        return _json_error('标题不能为空', status=400)
    if len(title) > 200:
        return _json_error('标题长度不能超过200个字符', status=400)

    valid_types = {choice[0] for choice in Discussion.TYPE_CHOICES}
    if type_value not in valid_types:
        return _json_error('讨论类型不合法', status=400)

    if not content:
        return _json_error('内容不能为空', status=400)

    try:
        with transaction.atomic():
            discussion = Discussion.objects.create(
                title=title,
                type=type_value,
                content=content,
                author=user,
            )
    except IntegrityError:
        return _json_error('创建讨论失败，请重试', status=500, code='db_error')
    except Exception as exc:
        return _json_error(f'创建讨论失败: {str(exc)}', status=500, code='db_error')

    return _json_success(
        '创建讨论成功',
        data=_serialize_discussion(discussion, include_content=False),
        status=201,
    )


@csrf_exempt
@jwt_required
@require_http_methods(['PUT', 'PATCH'])
def update_discussion(request, discussion_id):
    """
    更新讨论（作者本人或管理员）

    PUT /api/discussions/<id>/update

    请求体（JSON）：
    - title: 标题（可选，仅作者本人）
    - type: 类型（可选，仅作者本人）
    - content: Markdown 内容（可选，仅作者本人）
    - is_pinned: 是否置顶（可选，仅管理员）
    """
    user = request.user

    try:
        discussion_id = int(discussion_id)
    except (TypeError, ValueError):
        return _json_error('讨论ID格式错误', status=400)

    try:
        discussion = Discussion.objects.select_related('author').get(id=discussion_id)
    except Discussion.DoesNotExist:
        return _json_error('讨论不存在', status=404)

    # 检查权限：作者本人或管理员
    is_author = discussion.author.id == user.id
    is_admin = user.permission and user.permission >= 1
    
    if not is_author and not is_admin:
        return _json_error('无权修改此讨论', status=403)

    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    # 更新字段
    update_fields = []
    if 'title' in data:
        # 只有作者本人可以修改标题
        if not is_author:
            return _json_error('只有作者本人可以修改标题', status=403)
        title = (data.get('title') or '').strip()
        if not title:
            return _json_error('标题不能为空', status=400)
        if len(title) > 200:
            return _json_error('标题长度不能超过200个字符', status=400)
        discussion.title = title
        update_fields.append('title')

    if 'type' in data:
        # 只有作者本人可以修改类型
        if not is_author:
            return _json_error('只有作者本人可以修改类型', status=403)
        type_value = (data.get('type') or '').strip()
        valid_types = {choice[0] for choice in Discussion.TYPE_CHOICES}
        if type_value not in valid_types:
            return _json_error('讨论类型不合法', status=400)
        discussion.type = type_value
        update_fields.append('type')

    if 'content' in data:
        content = (data.get('content') or '').strip()
        if not content:
            return _json_error('内容不能为空', status=400)
        discussion.content = content
        update_fields.append('content')

    if 'is_pinned' in data:
        # 只有管理员可以修改置顶状态
        if not is_admin:
            return _json_error('只有管理员可以修改置顶状态', status=403)
        is_pinned = data.get('is_pinned')
        if not isinstance(is_pinned, bool):
            # 支持字符串形式的布尔值
            is_pinned = str(is_pinned).lower() in ('true', '1', 'yes')
        discussion.is_pinned = is_pinned
        update_fields.append('is_pinned')

    if not update_fields:
        return _json_error('没有需要更新的字段', status=400)

    try:
        discussion.save(update_fields=update_fields)
    except Exception as exc:
        return _json_error(f'更新讨论失败: {str(exc)}', status=500, code='db_error')

    return _json_success(
        '更新讨论成功',
        data=_serialize_discussion(discussion, include_content=True),
    )


@csrf_exempt
@jwt_required
@require_http_methods(['DELETE'])
def delete_discussion(request, discussion_id):
    """
    删除讨论（仅作者本人）

    DELETE /api/discussions/<id>/delete
    """
    user = request.user

    try:
        discussion_id = int(discussion_id)
    except (TypeError, ValueError):
        return _json_error('讨论ID格式错误', status=400)

    try:
        discussion = Discussion.objects.select_related('author').get(id=discussion_id)
    except Discussion.DoesNotExist:
        return _json_error('讨论不存在', status=404)

    # 检查权限：只有作者本人可以删除
    if discussion.author.id != user.id:
        return _json_error('无权删除此讨论', status=403)

    try:
        discussion.delete()
    except Exception as exc:
        return _json_error(f'删除讨论失败: {str(exc)}', status=500, code='db_error')

    return _json_success('删除讨论成功')


