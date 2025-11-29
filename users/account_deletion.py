# -*- coding: utf-8 -*-

"""
账户注销相关逻辑
"""
from typing import Tuple

from botocore.exceptions import ClientError
from django.conf import settings
from django.db import transaction

from .models import User
from .storage import get_s3_client


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


def delete_account_by_id(user_id: int) -> Tuple[bool, str]:
    """
    根据用户ID删除数据库记录并清理 MinIO 中的头像文件
    """
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user_id)

            # 删除 MinIO 中的头像文件夹
            cleanup_success, cleanup_message = _delete_avatar_folder(user.id)
            if not cleanup_success:
                return False, cleanup_message

            # 删除数据库记录
            user.delete()

        return True, '账户已注销'
    except User.DoesNotExist:
        return False, '用户不存在'
    except Exception as exc:
        return False, f'注销失败: {str(exc)}'

