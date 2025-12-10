# -*- coding: utf-8 -*-

"""
账户注销相关逻辑
"""
import threading
from typing import Tuple

from botocore.exceptions import ClientError
from django.conf import settings
from django.db import transaction

from .models import User
from .storage import delete_file_from_bucket, get_s3_client


def _delete_avatar_folder(user_id: int) -> Tuple[bool, str]:
    """
    删除 MinIO 中 avatars/{user_id}/ 下的所有对象
    """
    bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    prefix = f'avatars/{user_id}/'
    s3_client = get_s3_client()

    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        objects_batch = []
        deleted_any = False

        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
            contents = page.get('Contents', [])
            if not contents:
                continue

            deleted_any = True
            for obj in contents:
                objects_batch.append({'Key': obj['Key']})
                if len(objects_batch) == 1000:
                    s3_client.delete_objects(Bucket=bucket_name, Delete={'Objects': objects_batch})
                    objects_batch = []

        if objects_batch:
            s3_client.delete_objects(Bucket=bucket_name, Delete={'Objects': objects_batch})

        if deleted_any:
            return True, '头像文件已删除'
        return True, '未找到需要删除的头像文件'
    except ClientError as exc:
        message = exc.response.get('Error', {}).get('Message', str(exc))
        return False, f'删除头像失败: {message}'
    except Exception as exc:
        return False, f'删除头像失败: {str(exc)}'


def _extract_object_key_from_url(url: str) -> str:
    """
    从完整URL中提取object_key
    
    Args:
        url: 完整URL，如 "http://endpoint/bucket/avatars/1/avatar.jpg"
        
    Returns:
        str: object_key，如 "avatars/1/avatar.jpg"，如果无法提取则返回空字符串
    """
    if not url or not isinstance(url, str):
        return ''
    
    # 如果已经是object_key格式（以avatars/开头且不是完整URL）
    if url.startswith('avatars/') and not url.startswith('http'):
        return url
    
    # 如果是完整URL，尝试提取object_key
    if url.startswith('http://') or url.startswith('https://'):
        try:
            endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL', '').rstrip('/')
            bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
            url_prefix = f"{endpoint}/{bucket_name}/"
            
            if url.startswith(url_prefix):
                object_key = url[len(url_prefix):]
                return object_key
        except Exception:
            pass
    
    return ''


def _delete_user_avatar_async(user_id: int, avatar_url: str = ''):
    """
    异步删除用户头像文件（后台执行，不阻塞响应）
    
    Args:
        user_id: 用户ID
        avatar_url: 用户的头像URL
    """
    bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    prefix = f'avatars/{user_id}/'
    
    try:
        s3_client = get_s3_client()
        paginator = s3_client.get_paginator('list_objects_v2')
        objects_batch = []
        deleted_any = False

        # 删除 avatars/{user_id}/ 目录下的所有文件
        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
            contents = page.get('Contents', [])
            if not contents:
                continue

            deleted_any = True
            for obj in contents:
                objects_batch.append({'Key': obj['Key']})
                if len(objects_batch) == 1000:
                    s3_client.delete_objects(Bucket=bucket_name, Delete={'Objects': objects_batch})
                    objects_batch = []

        if objects_batch:
            s3_client.delete_objects(Bucket=bucket_name, Delete={'Objects': objects_batch})

        # 如果用户的 avatar_url 指向的是用户自己的头像文件（不在 avatars/{user_id}/ 目录下），
        # 尝试单独删除（虽然这种情况应该很少见）
        if avatar_url:
            object_key = _extract_object_key_from_url(avatar_url)
            
            # 如果提取到了object_key，且它属于该用户，且不在默认头像目录下
            if object_key:
                # 检查是否是用户自己的头像（avatars/{user_id}/...）
                user_avatar_prefix = f'avatars/{user_id}/'
                # 检查是否是默认头像（不应该删除）
                default_avatar_prefix = 'avatars/default/'
                
                if object_key.startswith(user_avatar_prefix):
                    # 属于用户自己的头像，但可能不在目录下（虽然这种情况很少见）
                    # 由于上面已经删除了整个目录，这里主要是为了健壮性
                    # 如果文件还存在，尝试删除
                    delete_file_from_bucket(object_key)
                elif not object_key.startswith(default_avatar_prefix):
                    # 既不是用户自己的头像目录，也不是默认头像
                    # 可能是旧数据或异常数据，尝试删除（如果存在）
                    # 但这种情况应该很少见，所以不强制要求成功
                    delete_file_from_bucket(object_key)

        if deleted_any:
            print(f"后台删除用户 {user_id} 的头像文件成功")
        else:
            print(f"用户 {user_id} 未找到需要删除的头像文件")
    except ClientError as exc:
        message = exc.response.get('Error', {}).get('Message', str(exc))
        print(f"后台删除用户 {user_id} 的头像文件失败: {message}")
    except Exception as exc:
        print(f"后台删除用户 {user_id} 的头像文件失败: {str(exc)}")


def delete_account_by_id(user_id: int) -> Tuple[bool, str]:
    """
    根据用户ID删除数据库记录并异步清理 MinIO 中的头像文件
    
    删除逻辑：
    1. 先删除数据库记录（快速返回）
    2. 异步删除 MinIO 中 avatars/{user_id}/ 目录下的所有文件（后台执行）
    3. 如果用户的 avatar_url 指向用户自己的头像文件，异步删除
    4. 不删除默认头像（avatars/default/...），因为多个用户可能共享
    
    注意：MinIO 删除操作在后台异步执行，即使失败也不影响数据库删除的成功返回
    """
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user_id)
            
            # 获取用户的头像URL，用于后续异步删除
            avatar_url = user.avatar_url or ''
            
            # 先删除数据库记录（快速返回）
            user.delete()

        # 异步删除 MinIO 中的头像文件（后台执行，不阻塞响应）
        threading.Thread(
            target=_delete_user_avatar_async,
            args=(user_id, avatar_url),
            daemon=True
        ).start()

        return True, '账户已注销'
    except User.DoesNotExist:
        return False, '用户不存在'
    except Exception as exc:
        return False, f'注销失败: {str(exc)}'

