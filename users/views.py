import json
import os
import random
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, Optional

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


def _json_error(message: str, status: int = 400, code: str = 'invalid_request', details: Optional[Dict] = None) -> JsonResponse:
    """返回JSON格式的错误响应"""
    response_data = {'code': code, 'message': message}
    if details:
        response_data['details'] = details
    return JsonResponse(response_data, status=status)


def _json_success(message: str, data: Optional[Dict] = None, status: int = 200) -> JsonResponse:
    """返回JSON格式的成功响应"""
    response_data = {'code': 'success', 'message': message}
    if data:
        response_data['data'] = data
    return JsonResponse(response_data, status=status)


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


def _get_default_avatar(user: User) -> str:
    """
    根据用户性别获取默认头像的object_key
    
    Args:
        user: 用户对象
        
    Returns:
        str: 默认头像的object_key，格式: avatars/default/boy1.png 或 avatars/default/girl1.png
    """
    # 根据性别选择前缀
    gender = user.gender or ''
    if gender == 'M':
        prefix = 'boy'
    elif gender == 'F':
        prefix = 'girl'
    else:
        # 如果性别未设置，默认使用boy
        prefix = 'boy'
    
    # 使用用户ID作为随机种子，确保同一用户每次获取的都是同一张默认头像
    random.seed(user.id)
    avatar_number = random.randint(1, 4)
    random.seed()  # 重置随机种子，避免影响其他随机数生成
    
    return f'avatars/default/{prefix}{avatar_number}.png'


def _serialize_user(user: User) -> Dict[str, Any]:
    """序列化用户信息（匹配设计文档格式）"""
    # 处理头像URL：如果存储的是object_key，转换为完整URL
    avatar_url = user.avatar_url or ''
    
    # 如果用户没有上传头像，使用默认头像
    if not avatar_url:
        avatar_url = _get_default_avatar(user)
    
    # 如果avatar_url是object_key格式（以avatars/开头且不是完整URL），直接生成URL
    # 优化：不在调用get_file_url函数，检查文件是否存在，直接生成URL
    if avatar_url.startswith('avatars/') and not avatar_url.startswith('http'):
        endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL').rstrip('/')
        bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME')
        avatar_url = f"{endpoint}/{bucket_name}/{avatar_url}"
    # 如果已经是完整URL，直接使用
    
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'gender': user.gender or '',
        'motto': user.motto or '',
        'avatar_url': avatar_url,
        'student_id': user.student_id or '',
        'class_name': user.class_name or '',
        'real_name': user.real_name or '',
        'status': user.status or 'normal',
        'last_login_time': user.last_login_time.isoformat() if user.last_login_time else None,
        'total_submissions': user.total_submissions,
        'accepted_submissions': user.accepted_submissions,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'permission': str(user.permission) if user.permission else '0',
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


def jwt_required(view_func):
    """
    JWT认证装饰器
    从请求头中提取JWT token，验证并获取用户信息
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # 从请求头获取token
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            return _json_error('未授权，请先登录', status=401, code='unauthorized')
        
        token = auth_header.split(' ')[1] if len(auth_header.split(' ')) > 1 else ''
        if not token:
            return _json_error('未授权，请先登录', status=401, code='unauthorized')
        
        try:
            # 验证并解码token
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            user_id = payload.get('user_id')
            
            if not user_id:
                return _json_error('无效的token', status=401, code='unauthorized')
            
            # 获取用户对象
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return _json_error('用户不存在', status=401, code='unauthorized')
            
            # 将用户对象附加到request
            request.user = user
            return view_func(request, *args, **kwargs)
            
        except jwt.ExpiredSignatureError:
            return _json_error('token已过期，请重新登录', status=401, code='unauthorized')
        except jwt.InvalidTokenError:
            return _json_error('无效的token', status=401, code='unauthorized')
        except Exception as e:
            return _json_error(f'认证失败: {str(e)}', status=401, code='unauthorized')
    
    return wrapper


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
    - avatar_url: 临时文件的 object_key（可选），格式如 "avatars/temp/{uuid}.{ext}"
    - student_id: 学号（可选）
    - class_name: 班级（可选）
    - real_name: 真实姓名（可选）
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
    student_id = (data.get('student_id') or '').strip()
    class_name = (data.get('class_name') or '').strip()
    real_name = (data.get('real_name') or '').strip()
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
            from huebRE.settings import ensure_database_and_tables
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
            # 先创建用户对象，但不保存avatar_url，因为需要user.id来生成默认头像
            user = User.objects.create(
                username=username,
                password_hash=hashed_password,
                email=email,
                gender=gender,
                motto=motto,
                student_id=student_id,
                class_name=class_name,
                real_name=real_name,
                status='normal',  # 新用户默认为正常状态
                avatar_url='',  # 临时设置为空，后续会更新
                last_login_time=datetime.now(timezone.utc),
            )

            # user.last_login_time = datetime.now(timezone.utc)
            # user.save(update_fields=['last_login_time'])
            
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
                        # 步骤4: 更新用户的avatar_url（保存object_key而不是URL，保持数据一致性）
                        user.avatar_url = final_avatar_key
                        user.save(update_fields=['avatar_url'])
                    else:
                        # 移动失败，清理临时文件，使用默认头像
                        print(f"警告: 文件移动失败: {move_message}, 临时文件: {temp_avatar_key}")
                        delete_file_from_bucket(temp_avatar_key)
                        # 使用默认头像
                        default_avatar = _get_default_avatar(user)
                        user.avatar_url = default_avatar
                        user.save(update_fields=['avatar_url'])
                except Exception as e:
                    # 移动文件时发生异常，清理临时文件，使用默认头像
                    print(f"警告: 移动头像文件时发生异常: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    if temp_avatar_key:
                        delete_file_from_bucket(temp_avatar_key)
                    # 使用默认头像
                    default_avatar = _get_default_avatar(user)
                    user.avatar_url = default_avatar
                    user.save(update_fields=['avatar_url'])
            else:
                # 如果没有上传头像，使用默认头像
                default_avatar = _get_default_avatar(user)
                user.avatar_url = default_avatar
                user.save(update_fields=['avatar_url'])
                    
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
            from huebRE.settings import ensure_database_and_tables
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
    
    # 检查用户状态
    if user.status == 'banned':
        return _json_error('账户已被封禁，请联系管理员', status=403, code='account_banned')

    # 更新最后登录时间
    user.last_login_time = datetime.now(timezone.utc)
    user.save(update_fields=['last_login_time'])

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
@jwt_required
@require_http_methods(['GET', 'PATCH'])
def user_profile(request):
    """
    用户信息管理
    
    GET /api/users/me - 获取当前用户信息
    PATCH /api/users/me - 更新用户信息
    
    认证: 需要JWT Token
    """
    user = request.user
    
    if request.method == 'GET':
        """获取当前用户信息"""
        return _json_success('获取成功', data=_serialize_user(user))
    
    elif request.method == 'PATCH':
        """
        更新用户信息
        
        请求参数（JSON格式）:
        - username: 新用户名（可选），3-50个字符，支持字母/数字/下划线
        - email: 新邮箱（可选），必须是有效的邮箱格式
        - gender: 性别（可选），可选值: 'M'（男）、'F'（女）、''（未设置）
        - motto: 个性签名（可选），最多80个字符
        - avatar_url: 头像URL（可选），格式: avatars/{user_id}/{filename} 或完整URL
        - student_id: 学号（可选）
        - class_name: 班级（可选）
        - real_name: 真实姓名（可选）
        """
        try:
            data = _parse_request_body(request)
        except ValueError as exc:
            return _json_error(str(exc), status=400, code='invalid_request')
        
        # 调试日志：打印接收到的数据
        print(f"[DEBUG] 接收到的更新数据: {data}")
        print(f"[DEBUG] 当前用户ID: {user.id}")
        
        update_fields = []
        errors = {}
        old_avatar_to_delete = None  # 用于保存成功后删除旧头像
        
        # 验证并更新用户名
        if 'username' in data:
            username = (data.get('username') or '').strip()
            if not username:
                errors['username'] = '用户名不能为空'
            elif len(username) < 3 or len(username) > 50:
                errors['username'] = '用户名长度需在3-50字符之间'
            else:
                # 检查用户名是否已被使用（排除当前用户）
                if User.objects.filter(username=username).exclude(id=user.id).exists():
                    return _json_error('用户名已被使用，请尝试其他名称', status=400, code='username_taken')
                user.username = username
                update_fields.append('username')
        
        # 验证并更新邮箱
        if 'email' in data:
            email = (data.get('email') or '').strip()
            if not email:
                errors['email'] = '邮箱不能为空'
            else:
                try:
                    validate_email(email)
                except ValidationError:
                    errors['email'] = '邮箱格式不正确'
                else:
                    # 检查邮箱是否已被使用（排除当前用户）
                    if User.objects.filter(email=email).exclude(id=user.id).exists():
                        return _json_error('邮箱已被注册，请尝试其他邮箱', status=400, code='email_taken')
                    user.email = email
                    update_fields.append('email')
        
        # 验证并更新性别
        if 'gender' in data:
            gender_value = data.get('gender')
            # 处理 None、空字符串、'M'、'F' 等情况
            if gender_value is None:
                gender = ''
            else:
                gender = str(gender_value).strip()
            
            if gender not in ['M', 'F', '']:
                errors['gender'] = f'性别值必须是 M（男）、F（女），收到: {repr(gender)}'
            else:
                user.gender = gender
                update_fields.append('gender')
        
        # 验证并更新个性签名
        if 'motto' in data:
            motto_value = data.get('motto')
            if motto_value is None:
                motto = ''
            else:
                motto = str(motto_value).strip()
            
            if len(motto) > 80:
                errors['motto'] = '个性签名最多80个字符'
            else:
                user.motto = motto
                update_fields.append('motto')
        
        # 验证并更新头像URL
        if 'avatar_url' in data:
            avatar_value = data.get('avatar_url')
            if avatar_value is None:
                avatar_value = ''
            else:
                avatar_value = str(avatar_value).strip()
            
            print(f"[DEBUG] 头像URL值: {repr(avatar_value)}")
            
            # 保存旧头像的object_key，用于后续删除
            old_avatar_key = None
            if user.avatar_url:
                # 如果当前存储的是完整URL，尝试提取object_key
                if user.avatar_url.startswith('http://') or user.avatar_url.startswith('https://'):
                    endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL').rstrip('/')
                    bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME')
                    url_prefix = f"{endpoint}/{bucket_name}/"
                    if user.avatar_url.startswith(url_prefix):
                        old_avatar_key = user.avatar_url[len(url_prefix):]
                    else:
                        # 外部URL，无法删除
                        old_avatar_key = None
                elif user.avatar_url.startswith('avatars/'):
                    # 已经是object_key格式
                    old_avatar_key = user.avatar_url
            
            if avatar_value:
                # 判断是object_key还是完整URL
                if avatar_value.startswith('http://') or avatar_value.startswith('https://'):
                    # 是完整URL，尝试从URL中提取object_key
                    # URL格式: http://endpoint/bucket/object_key
                    endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL').rstrip('/')
                    bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME')
                    url_prefix = f"{endpoint}/{bucket_name}/"
                    
                    print(f"[DEBUG] URL前缀: {url_prefix}")
                    
                    if avatar_value.startswith(url_prefix):
                        # 提取object_key
                        object_key = avatar_value[len(url_prefix):]
                        print(f"[DEBUG] 提取的object_key: {object_key}")
                        # 验证object_key格式
                        if object_key.startswith(f'avatars/{user.id}/'):
                            # 如果新头像和旧头像相同，不需要删除
                            if old_avatar_key != object_key:
                                user.avatar_url = object_key  # 存储object_key而不是URL
                                update_fields.append('avatar_url')
                                print(f"[DEBUG] 保存object_key: {object_key}")
                            else:
                                print(f"[DEBUG] 新头像与旧头像相同，无需更新")
                        else:
                            # 如果object_key格式不对，但可能是之前保存的完整URL，允许保存
                            if len(avatar_value) > 500:
                                errors['avatar_url'] = '头像URL最多500个字符'
                            else:
                                # 允许保存完整URL（兼容旧数据）
                                if old_avatar_key != avatar_value:
                                    user.avatar_url = avatar_value
                                    update_fields.append('avatar_url')
                                    print(f"[DEBUG] 保存完整URL（兼容模式）: {avatar_value[:50]}")
                    else:
                        # 是其他域名的URL，直接保存URL（可能是外部图片）
                        if len(avatar_value) > 500:
                            errors['avatar_url'] = '头像URL最多500个字符'
                        else:
                            if old_avatar_key != avatar_value:
                                user.avatar_url = avatar_value
                                update_fields.append('avatar_url')
                                print(f"[DEBUG] 保存外部URL: {avatar_value[:50]}")
                elif avatar_value.startswith('avatars/'):
                    # 检查是否是当前用户的头像路径
                    if avatar_value.startswith(f'avatars/{user.id}/'):
                        # 是object_key格式，直接保存
                        if len(avatar_value) > 500:
                            errors['avatar_url'] = '头像URL最多500个字符'
                        else:
                            # 如果新头像和旧头像相同，不需要删除
                            if old_avatar_key != avatar_value:
                                user.avatar_url = avatar_value
                                update_fields.append('avatar_url')
                                print(f"[DEBUG] 保存object_key: {avatar_value}")
                            else:
                                print(f"[DEBUG] 新头像与旧头像相同，无需更新")
                    else:
                        # 不是当前用户的头像路径，不允许
                        errors['avatar_url'] = f'头像URL必须是当前用户的头像路径（avatars/{user.id}/...），收到: {avatar_value[:50]}'
                else:
                    # 允许空字符串，但不允许其他格式
                    errors['avatar_url'] = f'头像URL必须是完整URL或object_key格式（avatars/{user.id}/...），收到: {avatar_value[:50]}'
            else:
                # 清空头像
                if old_avatar_key:
                    user.avatar_url = ''
                    update_fields.append('avatar_url')
                    print(f"[DEBUG] 清空头像")
                else:
                    print(f"[DEBUG] 头像本来就是空的，无需更新")
            
            # 保存旧头像的object_key，用于在保存成功后删除
            # 注意：这里不立即删除，而是在保存成功后再删除
            if 'avatar_url' in update_fields and old_avatar_key and old_avatar_key.startswith('avatars/'):
                # 检查新头像是否与旧头像不同
                new_avatar_key = user.avatar_url
                if new_avatar_key != old_avatar_key:
                    old_avatar_to_delete = old_avatar_key
        
        # 验证并更新学号
        if 'student_id' in data:
            student_id = (data.get('student_id') or '').strip()
            if len(student_id) > 50:
                errors['student_id'] = '学号最多50个字符'
            else:
                user.student_id = student_id
                update_fields.append('student_id')
        
        # 验证并更新班级
        if 'class_name' in data:
            class_name = (data.get('class_name') or '').strip()
            if len(class_name) > 100:
                errors['class_name'] = '班级最多100个字符'
            else:
                user.class_name = class_name
                update_fields.append('class_name')
        
        # 验证并更新真实姓名
        if 'real_name' in data:
            real_name = (data.get('real_name') or '').strip()
            if len(real_name) > 50:
                errors['real_name'] = '真实姓名最多50个字符'
            else:
                user.real_name = real_name
                update_fields.append('real_name')
        
        # 调试日志：打印验证错误
        if errors:
            print(f"[DEBUG] 验证错误: {errors}")
            return _json_error('请求参数不合法', status=400, code='invalid_request', details=errors)
        
        # 如果没有要更新的字段
        if not update_fields:
            print("[DEBUG] 没有需要更新的字段")
            return _json_success('没有需要更新的字段', data=_serialize_user(user))
        
        # 保存用户信息
        try:
            print(f"[DEBUG] 准备更新字段: {update_fields}")
            with transaction.atomic():
                user.save(update_fields=update_fields)
            print(f"[DEBUG] 更新成功")
            
            # 保存成功后，删除旧头像文件
            # 注意：如果旧头像是默认头像，不执行删除操作（默认头像是共享的，不应被删除）
            if old_avatar_to_delete:
                # 检查是否是默认头像
                if old_avatar_to_delete.startswith('avatars/default/'):
                    print(f"[DEBUG] 旧头像是默认头像，跳过删除: {old_avatar_to_delete}")
                else:
                    try:
                        delete_success, delete_message = delete_file_from_bucket(object_key=old_avatar_to_delete)
                        if delete_success:
                            print(f"[DEBUG] 成功删除旧头像: {old_avatar_to_delete}")
                        else:
                            print(f"[DEBUG] 删除旧头像失败: {delete_message}, object_key: {old_avatar_to_delete}")
                    except Exception as e:
                        print(f"[DEBUG] 删除旧头像时发生异常: {str(e)}")
                        # 删除失败不影响更新操作，只记录日志
            
            return _json_success('更新成功', data=_serialize_user(user))
        except IntegrityError as exc:
            print(f"[DEBUG] 数据库完整性错误: {exc}")
            # 检查是否是唯一性约束冲突
            if User.objects.filter(username=user.username).exclude(id=user.id).exists():
                return _json_error('用户名已被使用，请尝试其他名称', status=400, code='username_taken')
            if User.objects.filter(email=user.email).exclude(id=user.id).exists():
                return _json_error('邮箱已被注册，请尝试其他邮箱', status=400, code='email_taken')
            return _json_error('更新失败，请重试', status=500, code='db_error')
        except Exception as e:
            print(f"[DEBUG] 更新异常: {str(e)}")
            import traceback
            traceback.print_exc()
            return _json_error(f'更新失败: {str(e)}', status=500, code='db_error')


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def change_password(request):
    """
    修改密码
    
    POST /api/users/change-password - 修改当前用户密码
    
    认证: 需要JWT Token
    
    请求参数（JSON格式）:
    - old_password: 旧密码（必需）
    - new_password: 新密码（必需），至少6位
    """
    user = request.user
    
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='invalid_request')
    
    old_password = data.get('old_password', '').strip()
    new_password = data.get('new_password', '').strip()
    
    # 验证参数
    if not old_password:
        return _json_error('请输入旧密码', status=400, code='invalid_request')
    
    if not new_password:
        return _json_error('请输入新密码', status=400, code='invalid_request')
    
    if len(new_password) < 6:
        return _json_error('新密码长度至少6位', status=400, code='invalid_request')
    
    # 验证旧密码
    if not check_password(old_password, user.password_hash):
        return _json_error('旧密码不正确', status=400, code='invalid_password')
    
    # 检查新密码是否与旧密码相同
    if check_password(new_password, user.password_hash):
        return _json_error('新密码不能与旧密码相同', status=400, code='same_password')
    
    # 更新密码
    try:
        user.password_hash = make_password(new_password)
        user.save(update_fields=['password_hash'])
        return _json_success('密码修改成功')
    except Exception as e:
        print(f"[DEBUG] 修改密码异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return _json_error(f'修改密码失败: {str(e)}', status=500, code='db_error')


@csrf_exempt
@require_http_methods(['POST'])
def upload_temp_file(request):
    """
    上传临时文件到MinIO bucket（无需认证，用于注册阶段）
    
    请求参数（multipart/form-data）:
    - file: 文件对象（必需）
    - object_key: Minio对象键（必需），格式: avatars/temp/{uuid}/avatar.{ext}
    
    验证规则:
    - 文件类型: 仅支持图片 (image/*)
    - 文件大小: 最大5MB
    - object_key格式: 必须符合 avatars/temp/... 格式
    """
    # 检查文件
    if 'file' not in request.FILES:
        return _json_error('请选择要上传的文件', status=400, code='invalid_request')
    
    file = request.FILES['file']
    
    # 验证文件大小（最大5MB）
    max_size = 5 * 1024 * 1024  # 5MB
    if file.size > max_size:
        return _json_error('文件大小不能超过5MB', status=400, code='file_too_large')
    
    # 验证文件类型（仅支持图片）
    if not file.content_type or not file.content_type.startswith('image/'):
        return _json_error('只支持图片文件', status=400, code='invalid_file_type')
    
    # 获取object_key
    object_key = request.POST.get('object_key', '').strip()
    if not object_key:
        return _json_error('object_key参数不能为空', status=400, code='invalid_request')
    
    # 验证object_key格式（必须上传到临时目录）
    if not object_key.startswith('avatars/temp/'):
        return _json_error('临时文件只能上传到 avatars/temp/ 目录', status=400, code='invalid_path')
    
    # 上传文件
    try:
        success, message, file_url = upload_file_to_bucket(
            file=file,
            object_key=object_key,
            bucket_name=None,  # 使用默认bucket
        )
        
        if not success:
            print(f"临时文件上传失败: {message}, object_key: {object_key}")
            return _json_error(message, status=500, code='minio_error')
        
        # 返回成功响应（匹配设计文档格式）
        return JsonResponse(
            {
                'code': 'success',
                'message': '上传成功',
                'object_key': object_key,
                'url': file_url,
            },
            status=200,
        )
    except Exception as e:
        error_msg = f"上传临时文件时发生异常: {str(e)}"
        print(f"临时文件上传异常: {error_msg}")
        import traceback
        traceback.print_exc()
        return _json_error(error_msg, status=500, code='minio_error')


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def upload_file(request):
    """
    上传文件到MinIO bucket（需要认证）
    
    请求参数（multipart/form-data）:
    - file: 文件对象（必需）
    - object_key: Minio对象键（必需），格式: avatars/{user_id}/{filename}
    
    验证规则:
    - 文件类型: 仅支持图片 (image/*)
    - 文件大小: 最大5MB
    - object_key格式: 必须符合 avatars/{user_id}/... 格式，且user_id必须是当前用户
    """
    user = request.user
    
    # 检查文件
    if 'file' not in request.FILES:
        return _json_error('请选择要上传的文件', status=400, code='invalid_request')
    
    file = request.FILES['file']
    
    # 验证文件大小（最大5MB）
    max_size = 5 * 1024 * 1024  # 5MB
    if file.size > max_size:
        return _json_error('文件大小不能超过5MB', status=400, code='file_too_large')
    
    # 验证文件类型（仅支持图片）
    if not file.content_type or not file.content_type.startswith('image/'):
        return _json_error('只支持图片文件', status=400, code='invalid_file_type')
    
    # 获取object_key
    object_key = request.POST.get('object_key', '').strip()
    if not object_key:
        return _json_error('object_key参数不能为空', status=400, code='invalid_request')
    
    # 验证object_key格式（头像必须属于当前用户）
    if object_key.startswith('avatars/'):
        parts = object_key.split('/')
        if len(parts) >= 2:
            user_id_str = parts[1]
            try:
                user_id = int(user_id_str)
                if user_id != user.id:
                    return _json_error('无权上传到此路径', status=403, code='forbidden')
            except ValueError:
                return _json_error('object_key格式不正确', status=400, code='invalid_request')
    
    # 上传文件
    try:
        success, message, file_url = upload_file_to_bucket(
            file=file,
            object_key=object_key,
            bucket_name=None,  # 使用默认bucket
        )
        
        if not success:
            print(f"文件上传失败: {message}, object_key: {object_key}")
            return _json_error(message, status=500, code='minio_error')
        
        # 返回成功响应（匹配设计文档格式）
        return JsonResponse(
            {
                'code': 'success',
                'message': '上传成功',
                'object_key': object_key,
                'url': file_url,
            },
            status=200,
        )
    except Exception as e:
        error_msg = f"上传文件时发生异常: {str(e)}"
        print(f"文件上传异常: {error_msg}")
        import traceback
        traceback.print_exc()
        return _json_error(error_msg, status=500, code='minio_error')


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
