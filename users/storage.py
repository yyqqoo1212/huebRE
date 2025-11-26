"""
MinIO/S3 存储工具模块
提供文件上传、访问、删除等功能

文件存储结构设计（同一个bucket: onlinejudge）:
onlinejudge/
├── avatars/                    # 用户头像
│   └── {user_id}/{filename}
├── problems/                   # 题目相关
│   └── {problem_id}/
│       ├── testcases/         # 测试用例（输入输出文件）
│       │   ├── 1.in
│       │   ├── 1.out
│       │   └── ...
│       └── images/            # 题目图片
│           └── {filename}
├── courses/                    # 课程相关
│   └── {course_id}/
│       └── images/            # 课程图片
│           └── {filename}
└── discussions/               # 讨论区
    └── {discussion_id}/
        └── images/            # 讨论区图片
            └── {filename}
"""
import os
import uuid
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.http import HttpResponse


def get_s3_client():
    """获取S3客户端（兼容MinIO）"""
    return boto3.client(
        's3',
        endpoint_url=getattr(settings, 'AWS_S3_ENDPOINT_URL'),
        aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY'),
        use_ssl=getattr(settings, 'AWS_S3_USE_SSL', False),
        verify=getattr(settings, 'AWS_S3_VERIFY', False),
    )


def upload_file_to_bucket(
    file: UploadedFile,
    object_key: str,
    bucket_name: Optional[str] = None,
    content_type: Optional[str] = None,
    metadata: Optional[dict] = None
) -> Tuple[bool, str, Optional[str]]:
    """
    上传文件到指定的bucket
    
    Args:
        file: Django上传的文件对象
        object_key: 对象在bucket中的键（路径）
        bucket_name: bucket名称，如果为None则使用settings中的默认bucket
        content_type: 文件MIME类型，如果为None则自动检测
        metadata: 额外的元数据
        
    Returns:
        Tuple[bool, str, Optional[str]]: (是否成功, 消息, 文件URL)
    """
    if bucket_name is None:
        bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    
    try:
        s3_client = get_s3_client()
        
        # 准备上传参数
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type
        elif hasattr(file, 'content_type') and file.content_type:
            extra_args['ContentType'] = file.content_type
        
        if metadata:
            extra_args['Metadata'] = metadata
        
        # 上传文件
        file.seek(0)  # 确保文件指针在开头
        s3_client.upload_fileobj(
            file,
            bucket_name,
            object_key,
            ExtraArgs=extra_args if extra_args else None
        )
        
        # 生成文件URL
        aws_querystring_auth = getattr(settings, 'AWS_QUERYSTRING_AUTH', False)
        if aws_querystring_auth:
            # 生成预签名URL（带过期时间）
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': object_key},
                ExpiresIn=3600  # 1小时过期
            )
        else:
            # 生成公开URL
            endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL').rstrip('/')
            url = f"{endpoint}/{bucket_name}/{object_key}"
        
        return True, "文件上传成功", url
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        error_msg = f"上传文件失败 [{error_code}]: {error_message}"
        print(f"MinIO上传错误: {error_msg}")  # 调试日志
        return False, error_msg, None
    except Exception as e:
        error_msg = f"上传文件失败: {str(e)}"
        print(f"MinIO上传异常: {error_msg}")  # 调试日志
        import traceback
        traceback.print_exc()  # 打印完整堆栈跟踪
        return False, error_msg, None


def get_file_url(object_key: str, bucket_name: Optional[str] = None, expires_in: int = 3600, check_exists: bool = True) -> Optional[str]:
    """
    获取文件的访问URL
    
    Args:
        object_key: 对象在bucket中的键（路径）
        bucket_name: bucket名称，如果为None则使用settings中的默认bucket
        expires_in: URL过期时间（秒），仅当使用预签名URL时有效
        check_exists: 是否检查文件是否存在，默认为True
        
    Returns:
        Optional[str]: 文件URL，如果失败则返回None
    """
    if bucket_name is None:
        bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    
    try:
        # 无需检查文件是否存在
        if not check_exists:
            if getattr(settings, 'AWS_QUERYSTRING_AUTH', False):
                # 需要预签名URL时候，必须使用客户端
                s3_client = get_s3_client()
                url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': bucket_name, 'Key': object_key},
                    ExpiresIn=expires_in
                )
                return url
            else:
                # 生成公开URL,直接生成URL，无需调用API
                endpoint = settings.AWS_S3_ENDPOINT_URL.rstrip('/')

        # 需要检查文件是否存在
        s3_client = get_s3_client()
        
        try:
            s3_client.head_object(Bucket=bucket_name, Key=object_key)
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return None
            raise
        
        # 生成URL
        if getattr(settings, 'AWS_QUERYSTRING_AUTH', False):
            # 生成预签名URL
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': object_key},
                ExpiresIn=expires_in
            )
        else:
            # 生成公开URL
            endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL').rstrip('/')
            url = f"{endpoint}/{bucket_name}/{object_key}"
        
        return url
    except Exception as e:
        print(f"获取文件URL失败: {e}")
        return None


def download_file_from_bucket(object_key: str, bucket_name: Optional[str] = None) -> Optional[HttpResponse]:
    """
    从bucket下载文件
    
    Args:
        object_key: 对象在bucket中的键（路径）
        bucket_name: bucket名称，如果为None则使用settings中的默认bucket
        
    Returns:
        Optional[HttpResponse]: Django HttpResponse对象，如果失败则返回None
    """
    if bucket_name is None:
        bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    
    try:
        s3_client = get_s3_client()
        
        # 获取文件对象
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        
        # 获取文件内容
        file_content = response['Body'].read()
        
        # 获取 Content-Type
        content_type = response.get('ContentType', 'application/octet-stream')
        
        # 获取文件名
        filename = os.path.basename(object_key)
        
        # 创建 HttpResponse
        http_response = HttpResponse(file_content, content_type=content_type)
        http_response['Content-Disposition'] = f'attachment; filename="{filename}"'
        http_response['Content-Length'] = len(file_content)
        
        return http_response
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            return None
        print(f"下载文件失败: {e}")
        return None
    except Exception as e:
        print(f"下载文件失败: {e}")
        return None


def delete_file_from_bucket(object_key: str, bucket_name: Optional[str] = None) -> Tuple[bool, str]:
    """
    从bucket删除文件
    
    Args:
        object_key: 对象在bucket中的键（路径）
        bucket_name: bucket名称，如果为None则使用settings中的默认bucket
        
    Returns:
        Tuple[bool, str]: (是否成功, 消息)
    """
    if bucket_name is None:
        bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    
    try:
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=bucket_name, Key=object_key)
        return True, "文件删除成功"
    except ClientError as e:
        error_msg = f"删除文件失败: {e.response.get('Error', {}).get('Message', str(e))}"
        return False, error_msg
    except Exception as e:
        return False, f"删除文件失败: {str(e)}"


def move_file_in_bucket(
    source_key: str,
    dest_key: str,
    bucket_name: Optional[str] = None,
    delete_source: bool = True
) -> Tuple[bool, str]:
    """
    在bucket中移动文件（复制后删除源文件）
    
    Args:
        source_key: 源文件路径
        dest_key: 目标文件路径
        bucket_name: bucket名称，如果为None则使用settings中的默认bucket
        delete_source: 是否删除源文件，默认为True
        
    Returns:
        Tuple[bool, str]: (是否成功, 消息)
    """
    if bucket_name is None:
        bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    
    try:
        s3_client = get_s3_client()
        
        # 复制文件
        copy_source = {'Bucket': bucket_name, 'Key': source_key}
        s3_client.copy_object(
            CopySource=copy_source,
            Bucket=bucket_name,
            Key=dest_key
        )
        
        # 如果成功，删除源文件
        if delete_source:
            s3_client.delete_object(Bucket=bucket_name, Key=source_key)
        
        return True, "文件移动成功"
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        error_msg = f"移动文件失败 [{error_code}]: {error_message}"
        print(f"MinIO移动文件错误: {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"移动文件失败: {str(e)}"
        print(f"MinIO移动文件异常: {error_msg}")
        import traceback
        traceback.print_exc()
        return False, error_msg


def file_exists_in_bucket(object_key: str, bucket_name: Optional[str] = None) -> bool:
    """
    检查文件是否存在于bucket中
    
    Args:
        object_key: 对象在bucket中的键（路径）
        bucket_name: bucket名称，如果为None则使用settings中的默认bucket
        
    Returns:
        bool: 文件是否存在
    """
    if bucket_name is None:
        bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    
    try:
        s3_client = get_s3_client()
        s3_client.head_object(Bucket=bucket_name, Key=object_key)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        return False
    except Exception:
        return False


# ==================== 路径生成辅助函数 ====================

def get_temp_avatar_path(filename: str) -> str:
    """
    生成临时头像文件路径（注册时使用）
    
    Args:
        filename: 文件名（建议包含扩展名）
        
    Returns:
        str: 文件路径，如 "avatars/temp/uuid_filename.jpg"
    """
    unique_id = str(uuid.uuid4()).replace('-', '')
    _, ext = os.path.splitext(filename)
    unique_filename = f"{unique_id}{ext}"
    return f"avatars/temp/{unique_filename}"


def get_avatar_path(user_id: int, filename: str) -> str:
    """
    生成用户头像文件路径
    
    Args:
        user_id: 用户ID
        filename: 文件名（建议包含扩展名）
        
    Returns:
        str: 文件路径，如 "avatars/1/avatar.jpg"
    """
    # 如果文件名不包含扩展名，可以添加默认扩展名
    return f"avatars/{user_id}/{filename}"


def get_problem_testcase_path(problem_id: int, testcase_name: str) -> str:
    """
    生成题目测试用例文件路径
    
    Args:
        problem_id: 题目ID
        testcase_name: 测试用例文件名，如 "1.in", "1.out"
        
    Returns:
        str: 文件路径，如 "problems/1/testcases/1.in"
    """
    return f"problems/{problem_id}/testcases/{testcase_name}"


def get_problem_image_path(problem_id: int, filename: str) -> str:
    """
    生成题目图片文件路径
    
    Args:
        problem_id: 题目ID
        filename: 图片文件名
        
    Returns:
        str: 文件路径，如 "problems/1/images/image1.png"
    """
    # 如果文件名不包含扩展名，可以添加默认扩展名
    return f"problems/{problem_id}/images/{filename}"


def get_course_image_path(course_id: int, filename: str) -> str:
    """
    生成课程图片文件路径
    
    Args:
        course_id: 课程ID
        filename: 图片文件名
        
    Returns:
        str: 文件路径，如 "courses/1/images/course_cover.jpg"
    """
    return f"courses/{course_id}/images/{filename}"


def get_discussion_image_path(discussion_id: int, filename: str) -> str:
    """
    生成讨论区图片文件路径
    
    Args:
        discussion_id: 讨论ID
        filename: 图片文件名
        
    Returns:
        str: 文件路径，如 "discussions/1/images/image1.png"
    """
    return f"discussions/{discussion_id}/images/{filename}"


def generate_unique_filename(original_filename: str, prefix: Optional[str] = None) -> str:
    """
    生成唯一文件名（使用UUID避免文件名冲突）
    
    Args:
        original_filename: 原始文件名
        prefix: 可选的前缀
        
    Returns:
        str: 唯一文件名，如 "prefix_uuid_original.jpg"
    """
    # 获取文件扩展名
    _, ext = os.path.splitext(original_filename)
    # 生成UUID
    unique_id = str(uuid.uuid4()).replace('-', '')
    # 组合文件名
    if prefix:
        filename = f"{prefix}_{unique_id}{ext}"
    else:
        filename = f"{unique_id}{ext}"
    return filename

