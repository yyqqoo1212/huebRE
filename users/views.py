import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, OperationalError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import User
from .storage import (
    delete_file_from_bucket,
    download_file_from_bucket,
    file_exists_in_bucket,
    generate_unique_filename,
    get_avatar_path,
    get_file_url,
    get_temp_avatar_path,
    move_file_in_bucket,
    upload_file_to_bucket,
)


def _json_error(message: str, status: int = 400, code: str = 'invalid_request') -> JsonResponse:
    return JsonResponse({'success': False, 'code': code, 'message': message}, status=status)


def _parse_request_body(request) -> Dict[str, Any]:
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body.decode('utf-8') or '{}')
        except json.JSONDecodeError as exc:
            raise ValueError('JSON格式错误') from exc
    if request.POST:
        return request.POST.dict()
    if request.body:
        try:
            return json.loads(request.body.decode('utf-8'))
        except json.JSONDecodeError as exc:
            raise ValueError('JSON格式错误') from exc
    return {}


def _serialize_user(user: User) -> Dict[str, Any]:
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'gender': user.gender,
        'motto': user.motto,
        'avatar_url': user.avatar_url,
        'total_submissions': user.total_submissions,
        'accepted_submissions': user.accepted_submissions,
        'created_at': user.created_at.isoformat(),
        'permission': user.permission,
    }


def _generate_jwt(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': user.id,
        'username': user.username,
        'exp': now + timedelta(seconds=settings.JWT_EXP_DELTA_SECONDS),
        'iat': now,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token


def _set_session(request, user: User):
    request.session['user_id'] = user.id
    request.session['username'] = user.username


@csrf_exempt
@require_http_methods(['POST'])
def register(request):
    """
    用户注册
    
    工作流程（配合前端）：
    1. 前端：用户选择头像 → 自动上传到临时目录 avatars/temp/{uuid}/avatar.{ext}
    2. 前端：保存 object_key 到 avatarObjectKey，提交时作为 avatar_url 传递
    3. 后端：接收 avatar_url（实际上是临时文件的 object_key）
    4. 后端：创建用户（获取 user_id）
    5. 后端：将文件从临时目录移动到 avatars/{user_id}/{filename}
    6. 后端：更新用户的 avatar_url
    
    请求参数（JSON格式）:
    - username: 用户名（必需）
    - password: 密码（必需）
    - email: 邮箱（必需）
    - gender: 性别（可选），可选值: 'M'（男）、'F'（女）
    - motto: 个性签名（可选）
    - avatar_url: 临时文件的 object_key（可选），格式如 "avatars/temp/{uuid}/avatar.{ext}"
    """
    # 解析请求数据（JSON格式）
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    username = (data.get('username') or '').strip()
    raw_password = data.get('password')
    email = (data.get('email') or '').strip()
    gender = (data.get('gender') or '').strip()
    motto = (data.get('motto') or '').strip()
    temp_avatar_key = (data.get('avatar_url') or '').strip()  # 前端传递的是临时文件的 object_key

    if not username:
        return _json_error('用户名不能为空')
    if len(username) < 3 or len(username) > 50:
        return _json_error('用户名长度需在3-50字符之间')
    if not raw_password or len(raw_password) < 6:
        return _json_error('密码长度至少6位')
    if not email:
        return _json_error('邮箱不能为空')
    try:
        validate_email(email)
    except ValidationError:
        return _json_error('邮箱格式不正确')
    
    # 验证性别字段（如果提供了）
    if gender and gender not in ['M', 'F']:
        return _json_error('性别参数无效，可选值: M（男）、F（女）', status=400, code='invalid_gender')

    # 验证临时头像文件是否存在（如果提供了）
    if temp_avatar_key:
        if not file_exists_in_bucket(object_key=temp_avatar_key):
            return _json_error('头像文件不存在，请重新上传', status=404, code='avatar_not_found')

    # 尝试自动恢复数据库（如果不存在）
    try:
        if User.objects.filter(username=username).exists():
            # 如果注册失败，清理临时文件
            if temp_avatar_key:
                delete_file_from_bucket(temp_avatar_key)
            return _json_error('该用户名已存在', status=409, code='username_taken')
        if User.objects.filter(email=email).exists():
            # 如果注册失败，清理临时文件
            if temp_avatar_key:
                delete_file_from_bucket(temp_avatar_key)
            return _json_error('该邮箱已被注册', status=409, code='email_taken')
    except OperationalError:
        # 数据库不存在或表不存在，尝试恢复
        try:
            from huebonlinejudgeRE.settings import ensure_database_and_tables
            ensure_database_and_tables()
            # 恢复后重新检查
            if User.objects.filter(username=username).exists():
                if temp_avatar_key:
                    delete_file_from_bucket(temp_avatar_key)
                return _json_error('该用户名已存在', status=409, code='username_taken')
            if User.objects.filter(email=email).exists():
                if temp_avatar_key:
                    delete_file_from_bucket(temp_avatar_key)
                return _json_error('该邮箱已被注册', status=409, code='email_taken')
        except Exception:
            if temp_avatar_key:
                delete_file_from_bucket(temp_avatar_key)
            return _json_error('数据库连接失败，请稍后重试', status=503, code='db_unavailable')

    hashed_password = make_password(raw_password)

    try:
        with transaction.atomic():
            # 步骤2: 创建用户（获取user_id）
            user = User.objects.create(
                username=username,
                password_hash=hashed_password,
                email=email,
                gender=gender,
                motto=motto,
                avatar_url='',  # 初始值为空，如果有头像文件移动成功后会更新
            )
            
            # 步骤3: 如果有临时头像文件，移动到正式目录
            if temp_avatar_key:
                try:
                    # 从临时路径提取文件名和扩展名
                    # 临时路径格式: avatars/temp/{uuid}/avatar.{ext}
                    # 提取扩展名
                    _, ext = os.path.splitext(temp_avatar_key)
                    if not ext:
                        ext = '.jpg'  # 默认扩展名
                    
                    # 生成唯一文件名
                    unique_filename = generate_unique_filename(f'avatar{ext}', prefix='avatar')
                    
                    # 生成正式路径
                    final_avatar_key = get_avatar_path(user_id=user.id, filename=unique_filename)
                    
                    # 从临时目录移动到正式目录
                    move_success, move_message = move_file_in_bucket(
                        source_key=temp_avatar_key,
                        dest_key=final_avatar_key,
                        delete_source=True,  # 移动后删除临时文件
                    )
                    
                    if move_success:
                        # 步骤4: 更新用户的avatar_url
                        file_url = get_file_url(object_key=final_avatar_key)
                        if file_url:
                            user.avatar_url = file_url
                            user.save(update_fields=['avatar_url'])
                        else:
                            print(f"警告: 文件移动成功但无法生成URL, object_key: {final_avatar_key}")
                    else:
                        # 移动失败，清理临时文件
                        print(f"警告: 文件移动失败: {move_message}, 临时文件: {temp_avatar_key}")
                        delete_file_from_bucket(temp_avatar_key)
                except Exception as e:
                    # 移动文件时发生异常，清理临时文件
                    print(f"警告: 移动头像文件时发生异常: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    if temp_avatar_key:
                        delete_file_from_bucket(temp_avatar_key)
                    
    except IntegrityError as exc:
        # 如果注册失败，清理临时文件
        if temp_avatar_key:
            delete_file_from_bucket(temp_avatar_key)
        # 检查是否是唯一性约束冲突
        if User.objects.filter(username=username).exists():
            return _json_error('该用户名已存在', status=409, code='username_taken')
        if User.objects.filter(email=email).exists():
            return _json_error('该邮箱已被注册', status=409, code='email_taken')
        return _json_error('创建用户失败，请重试', status=500, code='db_error')
    except OperationalError:
        # 如果注册失败，清理临时文件
        if temp_avatar_key:
            delete_file_from_bucket(temp_avatar_key)
        return _json_error('数据库连接失败，请稍后重试', status=503, code='db_unavailable')
    except Exception as e:
        # 如果注册失败，清理临时文件
        if temp_avatar_key:
            delete_file_from_bucket(temp_avatar_key)
        return _json_error(f'注册失败: {str(e)}', status=500, code='register_failed')

    token = _generate_jwt(user)
    _set_session(request, user)

    return JsonResponse(
        {
            'success': True,
            'data': _serialize_user(user),
            'token': token,
            'token_type': 'Bearer',
            'expires_in': settings.JWT_EXP_DELTA_SECONDS,
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(['POST'])
def login(request):
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    username = (data.get('username') or '').strip()
    raw_password = data.get('password') or ''

    if not username or not raw_password:
        return _json_error('用户名和密码均为必填')

    # 尝试自动恢复数据库（如果不存在）
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return _json_error('用户名或密码错误', status=401, code='invalid_credentials')
    except OperationalError:
        # 数据库不存在或表不存在，尝试恢复
        try:
            from huebonlinejudgeRE.settings import ensure_database_and_tables
            ensure_database_and_tables()
            # 恢复后重新查询
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                return _json_error('用户名或密码错误', status=401, code='invalid_credentials')
        except Exception:
            return _json_error('数据库连接失败，请稍后重试', status=503, code='db_unavailable')

    if not check_password(raw_password, user.password_hash):
        return _json_error('用户名或密码错误', status=401, code='invalid_credentials')

    token = _generate_jwt(user)
    _set_session(request, user)

    return JsonResponse(
        {
            'success': True,
            'data': _serialize_user(user),
            'token': token,
            'token_type': 'Bearer',
            'expires_in': settings.JWT_EXP_DELTA_SECONDS,
        }
    )


@csrf_exempt
@require_http_methods(['POST'])
def upload_file(request):
    """
    上传文件到MinIO bucket
    
    请求参数:
    - file: 文件对象（multipart/form-data）
    - object_key: 可选，文件在bucket中的路径，如果不提供则使用文件名
    - bucket_name: 可选，bucket名称，如果不提供则使用settings中的默认bucket
    - folder: 可选，文件夹路径前缀
    """
    if 'file' not in request.FILES:
        return _json_error('请选择要上传的文件', status=400, code='no_file')
    
    file = request.FILES['file']
    if file.size == 0:
        return _json_error('文件不能为空', status=400, code='empty_file')
    
    # 获取可选参数
    object_key = request.POST.get('object_key', '').strip()
    bucket_name = request.POST.get('bucket_name', '').strip() or None
    folder = request.POST.get('folder', '').strip()
    
    # 如果没有指定object_key，则使用文件名
    if not object_key:
        filename = file.name
        # 如果指定了folder，添加到路径前
        if folder:
            folder = folder.rstrip('/') + '/'
            object_key = f"{folder}{filename}"
        else:
            object_key = filename
    else:
        # 如果指定了folder，添加到路径前
        if folder:
            folder = folder.rstrip('/') + '/'
            object_key = f"{folder}{object_key}"
    
    # 上传文件
    try:
        success, message, file_url = upload_file_to_bucket(
            file=file,
            object_key=object_key,
            bucket_name=bucket_name,
        )
        
        if not success:
            # 记录详细错误信息
            print(f"文件上传失败: {message}, object_key: {object_key}, bucket: {bucket_name}")
            return _json_error(message, status=500, code='upload_failed')
    except Exception as e:
        # 捕获所有异常，避免服务器崩溃
        error_msg = f"上传文件时发生异常: {str(e)}"
        print(f"文件上传异常: {error_msg}")
        import traceback
        traceback.print_exc()
        return _json_error(error_msg, status=500, code='upload_exception')
    
    return JsonResponse(
        {
            'success': True,
            'message': message,
            'data': {
                'object_key': object_key,
                'file_url': file_url,
                'filename': file.name,
                'size': file.size,
                'bucket': bucket_name or getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge'),
            },
        },
        status=201,
    )


@require_http_methods(['GET'])
def get_file(request):
    """
    获取文件的访问URL
    
    请求参数（URL参数）:
    - object_key: 文件在bucket中的路径（必需）
    - bucket_name: 可选，bucket名称
    - expires_in: 可选，URL过期时间（秒），默认3600
    """
    object_key = request.GET.get('object_key', '').strip()
    if not object_key:
        return _json_error('object_key参数不能为空', status=400, code='missing_object_key')
    
    bucket_name = request.GET.get('bucket_name', '').strip() or None
    expires_in = int(request.GET.get('expires_in', 3600))
    
    file_url = get_file_url(
        object_key=object_key,
        bucket_name=bucket_name,
        expires_in=expires_in,
    )
    
    if file_url is None:
        return _json_error('文件不存在或获取URL失败', status=404, code='file_not_found')
    
    return JsonResponse(
        {
            'success': True,
            'data': {
                'object_key': object_key,
                'file_url': file_url,
                'expires_in': expires_in,
                'bucket': bucket_name or getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge'),
            },
        }
    )


@require_http_methods(['GET'])
def download_file(request):
    """
    下载文件
    
    请求参数（URL参数）:
    - object_key: 文件在bucket中的路径（必需）
    - bucket_name: 可选，bucket名称
    """
    object_key = request.GET.get('object_key', '').strip()
    if not object_key:
        return _json_error('object_key参数不能为空', status=400, code='missing_object_key')
    
    bucket_name = request.GET.get('bucket_name', '').strip() or None
    
    http_response = download_file_from_bucket(
        object_key=object_key,
        bucket_name=bucket_name,
    )
    
    if http_response is None:
        return _json_error('文件不存在或下载失败', status=404, code='file_not_found')
    
    return http_response


@csrf_exempt
@require_http_methods(['DELETE', 'POST'])
def delete_file(request):
    """
    删除文件
    
    请求参数（URL参数或POST body）:
    - object_key: 文件在bucket中的路径（必需）
    - bucket_name: 可选，bucket名称
    """
    # 支持URL参数和POST body
    if request.method == 'DELETE':
        object_key = request.GET.get('object_key', '').strip()
        bucket_name = request.GET.get('bucket_name', '').strip() or None
    else:
        try:
            data = _parse_request_body(request)
            object_key = (data.get('object_key') or '').strip()
            bucket_name = (data.get('bucket_name') or '').strip() or None
        except ValueError as exc:
            return _json_error(str(exc), status=400, code='bad_json')
    
    if not object_key:
        return _json_error('object_key参数不能为空', status=400, code='missing_object_key')
    
    success, message = delete_file_from_bucket(
        object_key=object_key,
        bucket_name=bucket_name,
    )
    
    if not success:
        return _json_error(message, status=500, code='delete_failed')
    
    return JsonResponse(
        {
            'success': True,
            'message': message,
            'data': {
                'object_key': object_key,
                'bucket': bucket_name or getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge'),
            },
        }
    )


@require_http_methods(['GET'])
def check_file(request):
    """
    检查文件是否存在
    
    请求参数（URL参数）:
    - object_key: 文件在bucket中的路径（必需）
    - bucket_name: 可选，bucket名称
    """
    object_key = request.GET.get('object_key', '').strip()
    if not object_key:
        return _json_error('object_key参数不能为空', status=400, code='missing_object_key')
    
    bucket_name = request.GET.get('bucket_name', '').strip() or None
    
    exists = file_exists_in_bucket(
        object_key=object_key,
        bucket_name=bucket_name,
    )
    
    return JsonResponse(
        {
            'success': True,
            'data': {
                'object_key': object_key,
                'exists': exists,
                'bucket': bucket_name or getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge'),
            },
        }
    )
