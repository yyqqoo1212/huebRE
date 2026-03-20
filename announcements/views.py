# -*- coding: utf-8 -*-
import json

from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import SystemAnnouncement
from users.views import _json_error, _json_success, _parse_request_body, jwt_required


def _parse_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    return str(value).strip().lower() in ('true', '1', 'yes', 'y', 'on')


def _serialize_announcement(a: SystemAnnouncement) -> dict:
    return {
        'id': a.id,
        'title': a.title,
        'content': a.content,
        'is_important': a.is_important,
        'publisher_id': a.publisher_id,
        'publisher_name': a.publisher.username if a.publisher else '系统',
        'create_time': a.created_at.isoformat() if a.created_at else None,
        'update_time': a.updated_at.isoformat() if a.updated_at else None,
    }


@csrf_exempt
@require_http_methods(['GET'])
def list_announcements(request):
    """
    获取系统公告列表（公开）

    GET /api/announcements/list

    查询参数：
    - page: 页码（默认1）
    - page_size: 每页数量（默认20，最大100）
    - search: 标题关键字（可选）
    """
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
    except (TypeError, ValueError):
        page = 1
        page_size = 20

    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    search = (request.GET.get('search', '') or '').strip()

    qs = SystemAnnouncement.objects.all().order_by('-created_at')
    if search:
        qs = qs.filter(Q(title__icontains=search))

    total = qs.count()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    offset = (page - 1) * page_size

    items = list(qs[offset:offset + page_size])
    data = [_serialize_announcement(a) for a in items]

    return _json_success('获取公告列表成功', data={
        'announcements': data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_previous': page > 1,
        }
    })


@csrf_exempt
@require_http_methods(['GET'])
def get_announcement_detail(request, announcement_id: int):
    """
    获取单条公告详情（公开）
    GET /api/announcements/<announcement_id>
    """
    a = SystemAnnouncement.objects.filter(id=announcement_id).first()
    if not a:
        return _json_error('公告不存在', status=404, code='not_found')

    return _json_success('获取公告详情成功', data={
        'announcement': _serialize_announcement(a)
    })


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def create_announcement(request):
    """
    创建系统公告（管理员）
    POST /api/announcements/create
    请求体(JSON)：
    - title: 公告标题（必填）
    - content: 公告内容（必填）
    - is_important: 是否置顶（可选）
    """
    user = request.user
    if not user.permission or user.permission < 1:
        return _json_error('权限不足，需要管理员权限', status=403, code='permission_denied')

    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    is_important = _parse_bool(data.get('is_important', False), default=False)

    if not title:
        return _json_error('公告标题不能为空', status=400, code='invalid_request')
    if not content:
        return _json_error('公告内容不能为空', status=400, code='invalid_request')
    if len(title) > 200:
        return _json_error('公告标题长度不能超过200个字符', status=400, code='invalid_request')

    a = SystemAnnouncement.objects.create(
        title=title,
        content=content,
        is_important=is_important,
        publisher=user,
    )

    return _json_success(
        '创建公告成功',
        data={'announcement': _serialize_announcement(a)},
        status=201,
    )


@csrf_exempt
@jwt_required
@require_http_methods(['PATCH'])
def update_announcement(request, announcement_id: int):
    """
    更新系统公告（管理员）
    PATCH /api/announcements/<announcement_id>/update
    请求体(JSON)：title/content/is_important 可选
    """
    user = request.user
    if not user.permission or user.permission < 1:
        return _json_error('权限不足，需要管理员权限', status=403, code='permission_denied')

    a = SystemAnnouncement.objects.filter(id=announcement_id).first()
    if not a:
        return _json_error('公告不存在', status=404, code='not_found')

    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    update_fields = []
    if 'title' in data:
        title = (data.get('title') or '').strip()
        if not title:
            return _json_error('公告标题不能为空', status=400, code='invalid_request')
        if len(title) > 200:
            return _json_error('公告标题长度不能超过200个字符', status=400, code='invalid_request')
        a.title = title
        update_fields.append('title')

    if 'content' in data:
        content = (data.get('content') or '').strip()
        if not content:
            return _json_error('公告内容不能为空', status=400, code='invalid_request')
        a.content = content
        update_fields.append('content')

    if 'is_important' in data:
        a.is_important = _parse_bool(data.get('is_important', False), default=False)
        update_fields.append('is_important')

    if update_fields:
        a.save(update_fields=update_fields)

    return _json_success('更新公告成功', data={'announcement': _serialize_announcement(a)})


@csrf_exempt
@jwt_required
@require_http_methods(['DELETE'])
def delete_announcement(request, announcement_id: int):
    """
    删除系统公告（管理员）
    DELETE /api/announcements/<announcement_id>/delete
    """
    user = request.user
    if not user.permission or user.permission < 1:
        return _json_error('权限不足，需要管理员权限', status=403, code='permission_denied')

    a = SystemAnnouncement.objects.filter(id=announcement_id).first()
    if not a:
        return _json_error('公告不存在', status=404, code='not_found')

    a.delete()
    return _json_success('删除公告成功')

