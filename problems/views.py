# -*- coding: utf-8 -*-

from django.db import IntegrityError, transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django.http import HttpResponse, JsonResponse
from django.core.files.uploadedfile import UploadedFile
from django.core.cache import cache

from problems.models import Problem, ProblemData, Submission
from users.views import _json_error, _json_success, _parse_request_body, jwt_required
from users.storage import get_s3_client, get_problem_testcase_path, upload_file_to_bucket
from botocore.exceptions import ClientError
from django.conf import settings
import threading
import os
import zipfile
import tempfile
import shutil
from io import BytesIO
from uuid import uuid4
import hashlib
import requests
import json


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
    
    # 解析分页与筛选参数，容错处理，避免因为单个参数错误直接返回 400
    raw_page = request.GET.get('page', '1')
    raw_page_size = request.GET.get('page_size', '20')
    search = (request.GET.get('search', '') or '').strip()
    level = request.GET.get('level')
    auth = request.GET.get('auth')

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
            'author': problem.author,
            'create_time': problem.create_time.strftime('%Y-%m-%d %H:%M:%S') if problem.create_time else None,
            'auth': problem_data.auth,
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
        # 如果请求参数包含 allow_all=true，则不限制权限（用于管理员编辑）
        allow_all = request.GET.get('allow_all', '').lower() == 'true'
        if allow_all:
            problem = Problem.objects.select_related('stat').get(problem_id=problem_id)
        else:
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


@csrf_exempt
@jwt_required
@require_http_methods(['DELETE'])
def delete_problem(request, problem_id):
    """
    删除题目

    DELETE /api/problems/<problem_id>/delete

    - 删除 Problem 表中的题目
    - 删除 ProblemData 表中的统计信息
    - 删除 MinIO 中该题目的测试用例和图片目录：problems/{problem_id}/...
    """
    try:
        problem_id = int(problem_id)
    except (TypeError, ValueError):
        return _json_error('题目ID格式错误', status=400)

    try:
        problem = Problem.objects.get(problem_id=problem_id)
    except Problem.DoesNotExist:
        return _json_error('题目不存在', status=404)

    # TODO: 这里可以增加权限校验，只允许管理员或作者删除

    # 删除数据库记录（同步，确保题目立即在列表中消失）
    try:
        with transaction.atomic():
            ProblemData.objects.filter(problem=problem).delete()
            problem.delete()
    except Exception as exc:
        return _json_error(f'删除题目失败: {str(exc)}', status=500)

    # 异步删除 MinIO 中的相关文件（后台执行，不阻塞响应）
    def _delete_problem_files_async(p_id: int):
        bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
        prefix = f"problems/{p_id}/"
        try:
            s3_client = get_s3_client()
            continuation_token = None

            while True:
                if continuation_token:
                    resp = s3_client.list_objects_v2(
                        Bucket=bucket_name,
                        Prefix=prefix,
                        ContinuationToken=continuation_token,
                    )
                else:
                    resp = s3_client.list_objects_v2(
                        Bucket=bucket_name,
                        Prefix=prefix,
                    )

                objects = resp.get('Contents', [])
                if objects:
                    delete_payload = {
                        'Objects': [{'Key': obj['Key']} for obj in objects],
                        'Quiet': True,
                    }
                    s3_client.delete_objects(Bucket=bucket_name, Delete=delete_payload)

                if not resp.get('IsTruncated'):
                    break
                continuation_token = resp.get('NextContinuationToken')
        except Exception as exc:
            # 仅记录日志，不影响接口响应
            print(f"后台删除题目 {p_id} 的 MinIO 文件失败: {exc}")

    threading.Thread(target=_delete_problem_files_async, args=(problem_id,), daemon=True).start()

    return _json_success('删除题目成功', data={'problem_id': problem_id})


@csrf_exempt
@jwt_required
@require_http_methods(['PUT', 'PATCH'])
def update_problem(request, problem_id):
    """
    更新题目

    PUT /api/problems/<problem_id>/update

    请求体（JSON）示例：
    {
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
        problem_id = int(problem_id)
    except (TypeError, ValueError):
        return _json_error('题目ID格式错误', status=400)

    try:
        problem = Problem.objects.select_related('stat').get(problem_id=problem_id)
        problem_data = problem.stat
    except Problem.DoesNotExist:
        return _json_error('题目不存在', status=404)

    # TODO: 这里可以增加权限校验，只允许管理员或作者更新

    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    # 更新字段
    title = (data.get('title') or '').strip()
    if not title:
        return _json_error('标题不能为空', status=400)

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

    # 更新数据库记录
    try:
        with transaction.atomic():
            # 更新 Problem 表
            problem.title = title
            problem.content = content
            problem.input_description = input_description
            problem.output_description = output_description
            problem.input_demo = input_demo
            problem.output_demo = output_demo
            problem.time_limit = time_limit
            problem.memory_limit = memory_limit
            problem.hint = hint
            problem.auth = auth
            problem.save()

            # 更新 ProblemData 表
            problem_data.title = title
            problem_data.level = level
            problem_data.tag = tag
            problem_data.auth = auth
            problem_data.score = score
            problem_data.save()
    except Exception as exc:
        return _json_error(f'更新题目失败: {str(exc)}', status=500)

    return _json_success(
        '更新题目成功',
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
        }
    )


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def upload_and_validate_zip(request):
    """
    上传压缩包并解压验证

    POST /api/problems/upload-zip

    请求参数（multipart/form-data）:
    - file: 压缩包文件（.zip, .rar, .7z）

    返回:
    {
        "valid": true/false,
        "message": "验证结果消息",
        "files": ["1.in", "1.out", "2.in", "2.out", ...]  # 如果验证通过
    }
    """
    if 'file' not in request.FILES:
        return _json_error('请选择压缩包文件', status=400)

    zip_file = request.FILES['file']
    
    # 验证文件类型
    allowed_extensions = ['.zip', '.rar', '.7z']
    file_ext = os.path.splitext(zip_file.name)[1].lower()
    if file_ext not in allowed_extensions:
        return _json_error('只支持 .zip, .rar, .7z 格式的压缩包', status=400)

    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    extracted_dir = os.path.join(temp_dir, 'extracted')
    os.makedirs(extracted_dir, exist_ok=True)

    try:
        # 解压文件（目前只支持 zip）
        if file_ext == '.zip':
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                zip_ref.extractall(extracted_dir)
        else:
            # TODO: 支持 rar 和 7z 格式需要额外库
            return _json_error('暂不支持 .rar 和 .7z 格式，请使用 .zip 格式', status=400)

        # 验证文件
        files = []
        for root, dirs, filenames in os.walk(extracted_dir):
            for filename in filenames:
                rel_path = os.path.relpath(os.path.join(root, filename), extracted_dir)
                files.append(rel_path)

        # 只保留 .in 和 .out 文件
        testcase_files = [f for f in files if f.endswith(('.in', '.out'))]
        
        if not testcase_files:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _json_error('压缩包中没有找到 .in 或 .out 文件', status=400)

        # 验证文件命名规范
        in_files = sorted([f for f in testcase_files if f.endswith('.in')])
        out_files = sorted([f for f in testcase_files if f.endswith('.out')])

        # 检查文件名是否从 1 开始递增
        expected_count = max(len(in_files), len(out_files))
        valid = True
        missing_files = []

        for i in range(1, expected_count + 1):
            in_name = f"{i}.in"
            out_name = f"{i}.out"
            
            if in_name not in in_files:
                missing_files.append(in_name)
                valid = False
            if out_name not in out_files:
                missing_files.append(out_name)
                valid = False

        if not valid:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return JsonResponse({
                'code': 'success',
                'message': '压缩包不符合规范',
                'valid': False,
                'missing_files': missing_files
            }, status=200)

        # 生成缓存键，避免依赖 session
        temp_key = f"testcase_zip_{uuid4().hex}"
        cache.set(temp_key, {
            'temp_dir': temp_dir,
            'files': testcase_files,
        }, timeout=3600)  # 1 小时过期

        return JsonResponse({
            'code': 'success',
            'message': '压缩包验证通过',
            'valid': True,
            'files': sorted(testcase_files),
            'token': temp_key,
        }, status=200)

    except zipfile.BadZipFile:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _json_error('压缩包文件损坏或格式不正确', status=400)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _json_error(f'解压压缩包失败: {str(exc)}', status=500)


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def upload_testcase_files(request, problem_id):
    """
    上传手动输入的测试用例文件

    POST /api/problems/<problem_id>/upload-testcases

    请求体（JSON）:
    {
        "files": [
            {"name": "1.in", "content": "输入内容"},
            {"name": "1.out", "content": "输出内容"},
            ...
        ]
    }
    """
    try:
        problem_id = int(problem_id)
    except (TypeError, ValueError):
        return _json_error('题目ID格式错误', status=400)

    try:
        problem = Problem.objects.get(problem_id=problem_id)
    except Problem.DoesNotExist:
        return _json_error('题目不存在', status=404)

    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    files = data.get('files', [])
    if not files:
        return _json_error('没有要上传的文件', status=400)

    bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    uploaded_count = 0
    errors = []

    for file_info in files:
        file_name = file_info.get('name', '').strip()
        file_content = file_info.get('content', '')

        if not file_name or not file_name.endswith(('.in', '.out')):
            errors.append(f'文件名 {file_name} 格式不正确')
            continue

        try:
            # 创建临时文件
            temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=os.path.splitext(file_name)[1])
            temp_file.write(file_content)
            temp_file.close()

            # 上传到 MinIO
            object_key = get_problem_testcase_path(problem_id, file_name)
            
            with open(temp_file.name, 'rb') as f:
                # 创建 UploadedFile 对象
                uploaded_file = UploadedFile(
                    file=f,
                    name=file_name
                )
                
                success, message, url = upload_file_to_bucket(
                    file=uploaded_file,
                    object_key=object_key,
                    bucket_name=bucket_name
                )

                if success:
                    uploaded_count += 1
                else:
                    errors.append(f'上传 {file_name} 失败: {message}')

            # 删除临时文件
            os.unlink(temp_file.name)

        except Exception as exc:
            errors.append(f'处理 {file_name} 时出错: {str(exc)}')
            if 'temp_file' in locals():
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

    if errors:
        return _json_error(f'部分文件上传失败: {"; ".join(errors)}', status=500)
    
    return _json_success(f'成功上传 {uploaded_count} 个测试用例文件')


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def upload_extracted_testcases(request, problem_id):
    """
    上传解压后的测试用例文件

    POST /api/problems/<problem_id>/upload-extracted-testcases
    """
    try:
        problem_id = int(problem_id)
    except (TypeError, ValueError):
        return _json_error('题目ID格式错误', status=400)

    try:
        problem = Problem.objects.get(problem_id=problem_id)
    except Problem.DoesNotExist:
        return _json_error('题目不存在', status=404)

    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')

    temp_key = data.get('token')
    if not temp_key:
        return _json_error('缺少 token 参数，请先上传并验证压缩包', status=400)

    cache_data = cache.get(temp_key)
    if not cache_data:
        return _json_error('解压文件信息已过期，请重新上传压缩包', status=400)

    temp_dir = cache_data.get('temp_dir')
    testcase_files = cache_data.get('files') or []

    if not temp_dir or not os.path.exists(temp_dir):
        cache.delete(temp_key)
        return _json_error('临时文件已过期，请重新上传压缩包', status=400)

    bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    uploaded_count = 0
    errors = []

    try:
        for file_name in testcase_files:
            file_path = os.path.join(temp_dir, 'extracted', file_name)
            
            if not os.path.exists(file_path):
                continue

            try:
                # 上传到 MinIO
                object_key = get_problem_testcase_path(problem_id, os.path.basename(file_name))
                
                with open(file_path, 'rb') as f:
                    uploaded_file = UploadedFile(
                        file=f,
                        name=os.path.basename(file_name)
                    )
                    
                    success, message, url = upload_file_to_bucket(
                        file=uploaded_file,
                        object_key=object_key,
                        bucket_name=bucket_name
                    )

                    if success:
                        uploaded_count += 1
                    else:
                        errors.append(f'上传 {file_name} 失败: {message}')

            except Exception as exc:
                errors.append(f'处理 {file_name} 时出错: {str(exc)}')

        # 清理临时目录和 session
        shutil.rmtree(temp_dir, ignore_errors=True)
        cache.delete(temp_key)

        if errors:
            return _json_error(f'部分文件上传失败: {"; ".join(errors)}', status=500)
        
        return _json_success(f'成功上传 {uploaded_count} 个测试用例文件')

    except Exception as exc:
        # 确保清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)
        cache.delete(temp_key)
        return _json_error(f'上传测试用例失败: {str(exc)}', status=500)


@csrf_exempt
@jwt_required
@require_http_methods(['DELETE'])
def clear_problem_testcases(request, problem_id):
    """
    清空题目的测评数据（仅删除 MinIO 中 problems/{id}/testcases/ 下的文件）
    """
    try:
        problem_id = int(problem_id)
    except (TypeError, ValueError):
        return _json_error('题目ID格式错误', status=400)

    try:
        problem = Problem.objects.get(problem_id=problem_id)
    except Problem.DoesNotExist:
        return _json_error('题目不存在', status=404)

    bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    prefix = f"problems/{problem_id}/testcases/"

    try:
        s3_client = get_s3_client()
        continuation_token = None

        while True:
            if continuation_token:
                resp = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=prefix,
                    ContinuationToken=continuation_token,
                )
            else:
                resp = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=prefix,
                )

            objects = resp.get('Contents', [])
            if objects:
                delete_payload = {
                    'Objects': [{'Key': obj['Key']} for obj in objects],
                    'Quiet': True,
                }
                s3_client.delete_objects(Bucket=bucket_name, Delete=delete_payload)

            if not resp.get('IsTruncated'):
                break
            continuation_token = resp.get('NextContinuationToken')
    except Exception as exc:
        print(f"清空题目 {problem_id} 的测评数据失败: {exc}")

    return _json_success('清空测评数据完成', data={'problem_id': problem_id})


def _get_language_config(language: str) -> dict:
    """
    根据语言类型获取判题机语言配置
    
    Args:
        language: 语言类型 ('cpp', 'java', 'python', 'javascript')
        
    Returns:
        dict: 语言配置字典
    """
    language_configs = {
        'cpp': {
            'compile': {
                'src_name': 'main.cpp',
                'exe_name': 'main',
                'max_cpu_time': 3000,
                'max_real_time': 5000,
                'max_memory': 134217728,
                'compile_command': '/usr/bin/g++ -DONLINE_JUDGE -O2 -w -fmax-errors=3 -std=c++11 {src_path} -lm -o {exe_path}'
            },
            'run': {
                'command': '{exe_path}',
                'seccomp_rule': 'c_cpp',
                'env': ['LANG=en_US.UTF-8', 'LANGUAGE=en_US:en', 'LC_ALL=en_US.UTF-8']
            }
        },
        'java': {
            'compile': {
                'src_name': 'Main.java',
                'exe_name': 'Main',
                'max_cpu_time': 3000,
                'max_real_time': 5000,
                'max_memory': 134217728,
                'compile_command': '/usr/bin/javac -encoding UTF-8 {src_path}'
            },
            'run': {
                'command': '/usr/bin/java -cp {exe_dir} -Xmx{max_memory} Main',
                'seccomp_rule': 'general',
                'env': ['LANG=en_US.UTF-8', 'LANGUAGE=en_US:en', 'LC_ALL=en_US.UTF-8']
            }
        },
        'python': {
            'compile': {
                'src_name': 'solution.py',
                'exe_name': '__pycache__/solution.cpython-36.pyc',
                'max_cpu_time': 3000,
                'max_real_time': 5000,
                'max_memory': 134217728,
                'compile_command': '/usr/bin/python3 -m py_compile {src_path}'
            },
            'run': {
                'command': '/usr/bin/python3 {exe_path}',
                'seccomp_rule': 'general',
                'env': ['PYTHONIOENCODING=UTF-8', 'LANG=en_US.UTF-8', 'LANGUAGE=en_US:en', 'LC_ALL=en_US.UTF-8']
            }
        },
        'javascript': {
            'run': {
                'exe_name': 'solution.js',
                'command': '/usr/bin/node {exe_path}',
                'seccomp_rule': '',
                'env': ['LANG=en_US.UTF-8', 'LANGUAGE=en_US:en', 'LC_ALL=en_US.UTF-8'],
                'memory_limit_check_only': 1
            }
        }
    }
    
    return language_configs.get(language, language_configs['cpp'])


def judge_code(
    src: str,
    language: str,
    test_case: list,
    max_cpu_time: int,
    max_memory: int,
    output: bool = True,
    test_case_id: str = None,
    spj_version: str = None,
    spj_config: dict = None,
    spj_compile_config: dict = None,
    spj_src: str = None,
    io_mode: dict = None
) -> dict:
    """
    通用判题函数：调用判题机服务器运行代码
    
    Args:
        src: 源代码（必需）
        language: 语言类型（必需），可选值: 'cpp', 'java', 'python', 'javascript'
        test_case: 测试用例数组（可选），格式: [{"input": "...", "output": "..."}]
        max_cpu_time: 最大CPU时间（毫秒）（必需）
        max_memory: 最大内存（字节）（必需）
        output: 是否返回程序输出内容（默认True）
        test_case_id: 测试用例ID（可选，使用预定义的测试用例，与test_case二选一）
        spj_version: 特殊判题程序版本号（可选）
        spj_config: 特殊判题程序运行配置（可选）
        spj_compile_config: 特殊判题程序编译配置（可选）
        spj_src: 特殊判题程序源代码（可选）
        io_mode: 输入输出模式（可选）
        
    Returns:
        dict: 判题结果，格式:
        {
            'success': bool,  # 是否成功
            'error': str,     # 错误类型（如果失败）
            'message': str,   # 错误消息（如果失败）
            'data': list,     # 判题结果数组（如果成功），每个元素包含:
            #   {
            #       'cpu_time': int,      # CPU时间（毫秒）
            #       'real_time': int,     # 实际时间（毫秒）
            #       'memory': int,        # 内存使用（字节）
            #       'signal': int,        # 信号编号
            #       'exit_code': int,     # 程序退出码
            #       'error': int,          # 错误类型
            #       'result': int,         # 判题结果（0=成功, -1=答案错误, >0=各种错误）
            #       'test_case': str,      # 测试用例编号
            #       'output_md5': str,     # 输出MD5（如果设置了output）
            #       'output': str          # 程序输出（如果设置了output=True）
            #   }
        }
    """
    judge_server_url = getattr(settings, 'JUDGE_SERVER_URL', 'http://101.42.172.229:12358')
    judge_server_token = getattr(settings, 'JUDGE_SERVER_TOKEN', 'OYg4fMThGAjH80rojURhEz5GOBgSlMVm')
    
    # 计算Token的SHA256哈希值
    token_hash = hashlib.sha256(judge_server_token.encode('utf-8')).hexdigest()
    
    # 获取语言配置
    language_config = _get_language_config(language)
    
    # 构建请求体
    request_data = {
        'src': src,
        'language_config': language_config,
        'max_cpu_time': max_cpu_time,
        'max_memory': max_memory,
        'output': output
    }
    
    # 添加测试用例（test_case_id 和 test_case 二选一）
    if test_case_id:
        request_data['test_case_id'] = test_case_id
    elif test_case:
        request_data['test_case'] = test_case
    else:
        return {
            'success': False,
            'error': 'InvalidRequest',
            'message': '必须提供 test_case_id 或 test_case 之一'
        }
    
    # 添加特殊判题程序相关参数（如果提供）
    if spj_version:
        request_data['spj_version'] = spj_version
    if spj_config:
        request_data['spj_config'] = spj_config
    if spj_compile_config:
        request_data['spj_compile_config'] = spj_compile_config
    if spj_src:
        request_data['spj_src'] = spj_src
    if io_mode:
        request_data['io_mode'] = io_mode
    
    # 发送请求到判题机
    try:
        response = requests.post(
            f'{judge_server_url}/judge',
            headers={
                'X-Judge-Server-Token': token_hash,
                'Content-Type': 'application/json'
            },
            json=request_data,
            timeout=60  # 60秒超时（判题可能需要较长时间）
        )
        
        response.raise_for_status()
        result = response.json()
        
        # 检查是否有错误
        if result.get('err'):
            error_type = result.get('err')
            error_message = f"判题机错误: {error_type}"
            
            # 如果是编译错误，尝试从data中获取错误信息
            if error_type == 'CompileError' and result.get('data'):
                compile_error = result.get('data')
                if isinstance(compile_error, str):
                    error_message = f"编译错误:\n{compile_error}"
                elif isinstance(compile_error, dict) and compile_error.get('message'):
                    error_message = f"编译错误:\n{compile_error.get('message')}"
            
            return {
                'success': False,
                'error': error_type,
                'message': error_message,
                'data': result.get('data')  # 可能包含编译错误信息
            }
        
        # 返回完整的判题结果JSON
        return {
            'success': True,
            'data': result.get('data', [])
        }
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'error': 'Timeout',
            'message': '判题机请求超时，请稍后重试'
        }
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': 'RequestError',
            'message': f'判题机请求失败: {str(e)}'
        }
    except Exception as e:
        return {
            'success': False,
            'error': 'UnknownError',
            'message': f'判题机调用异常: {str(e)}'
        }


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def run_test(request, problem_id):
    """
    运行自测（调用判题机运行代码）
    
    POST /api/problems/{problem_id}/run-test
    
    请求参数（JSON格式）:
    - code: 源代码（必需）
    - language: 语言类型（必需），可选值: 'cpp', 'java', 'python', 'javascript'
    - test_input: 测试用例输入（必需）
    
    认证: 需要JWT Token
    """
    try:
        problem_id = int(problem_id)
    except (TypeError, ValueError):
        return _json_error('题目ID格式错误', status=400)
    
    # 检查题目是否存在
    try:
        problem = Problem.objects.get(problem_id=problem_id)
    except Problem.DoesNotExist:
        return _json_error('题目不存在', status=404)
    
    # 解析请求数据
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')
    
    code = data.get('code', '').strip()
    language = data.get('language', '').strip()
    test_input = data.get('test_input', '').strip()
    
    # 验证参数
    if not code:
        return _json_error('代码不能为空', status=400)
    
    if not language:
        return _json_error('语言类型不能为空', status=400)
    
    if language not in ['cpp', 'java', 'python', 'javascript']:
        return _json_error('不支持的语言类型', status=400)
    
    if not test_input:
        return _json_error('测试用例输入不能为空', status=400)
    
    # 获取题目的时间和内存限制（从Problem模型获取）
    max_cpu_time = problem.time_limit if problem else 1000  # 默认1000ms
    max_memory = (problem.memory_limit * 1024 * 1024) if problem else 134217728  # 转换为字节，默认128MB
    
    # 检查用户输入的测试用例是否匹配题目的测试样例
    # 如果匹配，则进行答案对比；如果不匹配，则不进行答案对比
    expected_output = ''
    is_matched_sample = False  # 标记是否匹配了测试样例
    input_demo = problem.input_demo or ''
    output_demo = problem.output_demo or ''
    
    if input_demo and output_demo:
        # 解析样例（用 | 分隔）
        input_list = [s.strip() for s in input_demo.split('|') if s.strip()]
        output_list = [s.strip() for s in output_demo.split('|') if s.strip()]
        
        # 检查用户输入是否匹配某个样例的输入
        # 去除首尾空白字符后进行比较
        test_input_normalized = test_input.strip()
        for i, sample_input in enumerate(input_list):
            if sample_input == test_input_normalized:
                # 找到匹配的样例，使用对应的输出作为期望输出
                # 去除末尾的空白字符（空格、制表符、换行符等），避免格式问题导致答案错误
                if i < len(output_list):
                    expected_output = output_list[i].rstrip()  # 只去除末尾空白，保留开头的空白（如果有）
                    is_matched_sample = True  # 标记已匹配测试样例
                break
    
    # 构建测试用例数组
    # 如果匹配了样例，则进行答案对比；否则不进行答案对比
    test_case = [{
        'input': test_input,
        'output': expected_output  # 如果匹配样例，则进行答案对比；否则为空字符串，不进行答案对比
    }]
    
    # 调用通用判题函数
    judge_result = judge_code(
        src=code,
        language=language,
        test_case=test_case,
        max_cpu_time=max_cpu_time,
        max_memory=max_memory,
        output=True
    )
    
    # 如果判题失败（如编译错误），直接返回错误信息
    if not judge_result['success']:
        error_data = judge_result.get('data')
        if error_data:
            # 如果有详细的错误信息，使用它
            if isinstance(error_data, str):
                output_text = error_data
            elif isinstance(error_data, dict):
                output_text = error_data.get('message', judge_result['message'])
            else:
                output_text = judge_result['message']
        else:
            output_text = judge_result['message']
        
        return _json_success('运行完成', data={
            'output': output_text,
            'result': -2,  # 编译错误或系统错误
            'error': judge_result.get('error'),
            'raw_result': judge_result  # 返回完整的JSON结果
        })
    
    results = judge_result.get('data', [])
    if not results or len(results) == 0:
        return _json_error('判题机返回结果为空', status=500)
    
    result = results[0]  # 只有一个测试用例
    
    # 构建返回结果
    output_text = ''
    result_code = result.get('result', 5)
    
    # 检查是否有编译错误（通过err字段判断）
    if result_code == 5:  # SYSTEM_ERROR，可能是编译错误
        output_text = '系统错误'
        # 如果有输出信息，也显示出来
        if result.get('output'):
            output_text = result.get('output')
    elif result_code == 1:  # CPU_TIME_LIMIT_EXCEEDED
        output_text = f"CPU时间超限（限制: {max_cpu_time}ms，实际: {result.get('cpu_time', 0)}ms）"
        if result.get('output'):
            output_text = result.get('output') + '\n\n' + output_text
    elif result_code == 2:  # REAL_TIME_LIMIT_EXCEEDED
        output_text = f"实际时间超限（限制: {max_cpu_time * 2}ms，实际: {result.get('real_time', 0)}ms）"
        if result.get('output'):
            output_text = result.get('output') + '\n\n' + output_text
    elif result_code == 3:  # MEMORY_LIMIT_EXCEEDED
        memory_mb = result.get('memory', 0) / (1024 * 1024)
        max_memory_mb = max_memory / (1024 * 1024)
        output_text = f"内存超限（限制: {max_memory_mb:.2f}MB，实际: {memory_mb:.2f}MB）"
        if result.get('output'):
            output_text = result.get('output') + '\n\n' + output_text
    elif result_code == 4:  # RUNTIME_ERROR
        exit_code = result.get('exit_code', 0)
        signal = result.get('signal', 0)
        if signal:
            output_text = f"运行时错误（信号: {signal}，退出码: {exit_code}）"
        else:
            output_text = f"运行时错误（退出码: {exit_code}）"
        if result.get('output'):
            output_text = result.get('output') + '\n\n' + output_text
    elif result_code == 0:  # SUCCESS
        # 程序运行成功，显示输出
        output_text = result.get('output', '')
        if not output_text:
            output_text = '(程序运行成功，但无输出)'
    elif result_code == -1:  # WRONG_ANSWER
        # 如果输入不是测试样例，且程序正常运行完成，则视为 Accepted
        # 如果输入是测试样例，则使用判题机返回的结果（Wrong Answer）
        exit_code = result.get('exit_code', 0)
        error = result.get('error', 0)
        
        # 如果程序正常运行完成（没有运行时错误），且输入不匹配测试样例，则视为 Accepted
        if not is_matched_sample and exit_code == 0 and error == 0:
            # 程序正常运行完成，但不是测试样例，视为 Accepted
            result_code = 0  # 改为 Accepted
            output_text = result.get('output', '')
            if not output_text:
                output_text = '(程序运行成功，但无输出)'
        else:
            # 匹配了测试样例，使用判题机返回的结果（Wrong Answer）
            output_text = result.get('output', '')
            if not output_text:
                output_text = '(程序运行成功，但无输出)'
    else:
        output_text = f"未知错误（结果代码: {result_code}）"
        if result.get('output'):
            output_text = result.get('output') + '\n\n' + output_text
    
    # 如果输入不是测试样例，且程序正常运行完成，将 result 设置为 0（Accepted）
    if not is_matched_sample:
        exit_code = result.get('exit_code', 0)
        error = result.get('error', 0)
        # 如果程序正常运行完成（没有运行时错误、超时、内存超限等），则视为 Accepted
        if exit_code == 0 and error == 0 and result_code not in [1, 2, 3, 4, 5]:
            result_code = 0  # 改为 Accepted
    
    # 更新 result 对象中的 result 字段
    result['result'] = result_code
    
    # 返回结果：只返回必要的字段，避免冗余
    # 自测模式下，直接返回判题机的原始结果即可
    return _json_success('运行完成', data=result)


def _load_testcases_from_minio(problem_id: int) -> list:
    """
    从MinIO加载题目的所有测试用例
    
    Args:
        problem_id: 题目ID
        
    Returns:
        list: 测试用例数组，格式: [{"input": "...", "output": "..."}]
    """
    bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'onlinejudge')
    s3_client = get_s3_client()
    testcase_prefix = f"problems/{problem_id}/testcases/"
    
    testcases = []
    
    try:
        # 列出所有测试用例文件
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=testcase_prefix
        )
        
        if 'Contents' not in response:
            return testcases
        
        # 收集所有.in和.out文件
        in_files = {}
        out_files = {}
        
        for obj in response['Contents']:
            key = obj['Key']
            filename = os.path.basename(key)
            
            if filename.endswith('.in'):
                # 提取测试用例编号（例如：1.in -> 1）
                testcase_num = filename[:-3]
                in_files[testcase_num] = key
            elif filename.endswith('.out'):
                testcase_num = filename[:-4]
                out_files[testcase_num] = key
        
        # 按测试用例编号排序
        testcase_nums = sorted(set(list(in_files.keys()) + list(out_files.keys())))
        
        # 读取每个测试用例的输入和输出
        for num in testcase_nums:
            input_content = ''
            output_content = ''
            
            # 读取输入文件
            if num in in_files:
                try:
                    response = s3_client.get_object(Bucket=bucket_name, Key=in_files[num])
                    input_content = response['Body'].read().decode('utf-8')
                except Exception as e:
                    print(f"读取测试用例 {num}.in 失败: {e}")
                    continue
            
            # 读取输出文件（可选）
            if num in out_files:
                try:
                    response = s3_client.get_object(Bucket=bucket_name, Key=out_files[num])
                    output_content = response['Body'].read().decode('utf-8')
                except Exception as e:
                    print(f"读取测试用例 {num}.out 失败: {e}")
                    # 输出文件不存在也可以继续
            
            if input_content:  # 至少要有输入文件
                testcases.append({
                    'input': input_content,
                    'output': output_content
                })
        
        return testcases
        
    except ClientError as e:
        print(f"从MinIO加载测试用例失败: {e}")
        return []
    except Exception as e:
        print(f"加载测试用例时出错: {e}")
        return []


@csrf_exempt
@jwt_required
@require_http_methods(['POST'])
def submit_code(request, problem_id):
    """
    提交代码进行判题（使用题目的时间限制和内存限制）
    
    POST /api/problems/{problem_id}/submit
    
    请求参数（JSON格式）:
    - code: 源代码（必需）
    - language: 语言类型（必需），可选值: 'cpp', 'java', 'python', 'javascript'
    
    认证: 需要JWT Token
    
    返回: 判题结果
    {
        "success": true,
        "message": "判题完成",
        "data": {
            "success": bool,
            "error": str,
            "message": str,
            "data": list  # 判题结果数组
        }
    }
    """
    try:
        problem_id = int(problem_id)
    except (TypeError, ValueError):
        return _json_error('题目ID格式错误', status=400)
    
    # 检查题目是否存在
    try:
        problem = Problem.objects.get(problem_id=problem_id)
    except Problem.DoesNotExist:
        return _json_error('题目不存在', status=404)
    
    # 解析请求数据
    try:
        data = _parse_request_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400, code='bad_json')
    
    code = data.get('code', '').strip()
    language = data.get('language', '').strip()
    
    # 验证参数
    if not code:
        return _json_error('代码不能为空', status=400)
    
    if not language:
        return _json_error('语言类型不能为空', status=400)
    
    if language not in ['cpp', 'java', 'python', 'javascript']:
        return _json_error('不支持的语言类型，支持: cpp, java, python, javascript', status=400)
    
    # 获取题目的时间和内存限制（从Problem模型获取）
    # time_limit 单位是毫秒，memory_limit 单位是MB
    max_cpu_time = problem.time_limit  # 题目设置的时间限制（毫秒）
    max_memory = problem.memory_limit * 1024 * 1024  # 转换为字节
    
    # 从MinIO加载测试用例
    test_cases = _load_testcases_from_minio(problem_id)
    
    if not test_cases:
        return _json_error('题目没有测试用例，请联系管理员', status=400)
    
    # 获取当前用户
    user = request.user
    
    # 创建提交记录（初始状态为Judging）
    code_length = len(code.encode('utf-8'))
    submission = Submission.objects.create(
        problem=problem,
        user=user,
        code=code,
        language=language,
        status=Submission.STATUS_JUDGING,
        code_length=code_length,
        result={}
    )
    
    try:
        # 调用通用判题函数，使用题目的时间限制和内存限制
        judge_result = judge_code(
            src=code,
            language=language,
            test_case=test_cases,
            max_cpu_time=max_cpu_time,  # 使用题目设置的时间限制
            max_memory=max_memory,      # 使用题目设置的内存限制
            output=True
        )
        
        # 处理判题结果
        if not judge_result.get('success', False):
            # 判题失败（如编译错误）
            error_type = judge_result.get('error', 'SystemError')
            error_message = judge_result.get('message', '判题失败')
            
            # 判断错误类型
            if error_type == 'CompileError':
                final_status = Submission.STATUS_COMPILE_ERROR
            else:
                final_status = Submission.STATUS_SYSTEM_ERROR
            
            # 更新提交记录
            submission.status = final_status
            submission.result = {
                'error': error_type,
                'message': error_message,
                'data': judge_result.get('data')
            }
            submission.save()
            
            # 更新题目统计
            problem_data, _ = ProblemData.objects.get_or_create(problem=problem)
            problem_data.submission += 1
            if final_status == Submission.STATUS_COMPILE_ERROR:
                problem_data.ce += 1
            problem_data.save()
            
            return _json_success('判题完成', data={
                'submission_id': submission.submission_id,
                'status': final_status,
                'status_text': submission.get_status_display(),
                'judge_result': judge_result
            })
        
        # 判题成功，处理测试用例结果
        test_results = judge_result.get('data', [])
        
        # 计算最终状态：只有所有测试用例都是Accepted才显示Accepted，否则显示第一个错误状态
        final_status = Submission.STATUS_ACCEPTED
        first_error_status = None
        max_cpu_time_used = 0
        max_memory_used = 0
        
        for result in test_results:
            result_code = result.get('result', -1)
            cpu_time = result.get('cpu_time', 0)
            memory = result.get('memory', 0)
            
            # 更新最大时间和内存
            max_cpu_time_used = max(max_cpu_time_used, cpu_time)
            max_memory_used = max(max_memory_used, memory)
            
            # 检查结果状态（只处理第一个错误）
            if result_code != 0 and first_error_status is None:  # 不是Accepted且还没有记录错误
                # 记录第一个错误状态
                if result_code == -1:
                    first_error_status = Submission.STATUS_WRONG_ANSWER
                elif result_code == 1 or result_code == 2:
                    first_error_status = Submission.STATUS_TIME_LIMIT_EXCEEDED
                elif result_code == 3:
                    first_error_status = Submission.STATUS_MEMORY_LIMIT_EXCEEDED
                elif result_code == 4:
                    first_error_status = Submission.STATUS_RUNTIME_ERROR
                else:
                    first_error_status = Submission.STATUS_SYSTEM_ERROR
        
        # 如果有错误，使用第一个错误状态；否则使用Accepted
        if first_error_status is not None:
            final_status = first_error_status
        
        # 更新提交记录
        submission.status = final_status
        submission.cpu_time = max_cpu_time_used
        submission.memory = max_memory_used
        submission.result = {
            'test_results': test_results,
            'total_tests': len(test_results),
            'passed_tests': sum(1 for r in test_results if r.get('result', -1) == 0)
        }
        submission.save()
        
        # 更新题目统计
        problem_data, _ = ProblemData.objects.get_or_create(problem=problem)
        problem_data.submission += 1
        
        if final_status == Submission.STATUS_ACCEPTED:
            problem_data.ac += 1
        elif final_status == Submission.STATUS_WRONG_ANSWER:
            problem_data.wr += 1
        elif final_status == Submission.STATUS_TIME_LIMIT_EXCEEDED:
            problem_data.tle += 1
        elif final_status == Submission.STATUS_MEMORY_LIMIT_EXCEEDED:
            problem_data.mle += 1
        elif final_status == Submission.STATUS_RUNTIME_ERROR:
            problem_data.re += 1
        elif final_status == Submission.STATUS_COMPILE_ERROR:
            problem_data.ce += 1
        
        problem_data.save()
        
        # 更新用户统计
        user.total_submissions += 1
        if final_status == Submission.STATUS_ACCEPTED:
            user.accepted_submissions += 1
        user.save(update_fields=['total_submissions', 'accepted_submissions'])
        
        return _json_success('判题完成', data={
            'submission_id': submission.submission_id,
            'status': final_status,
            'status_text': submission.get_status_display(),
            'cpu_time': max_cpu_time_used,
            'memory': max_memory_used,
            'code_length': code_length,
            'judge_result': judge_result
        })
        
    except Exception as e:
        # 判题过程中出现异常
        submission.status = Submission.STATUS_SYSTEM_ERROR
        submission.result = {'error': str(e)}
        submission.save()
        
        # 更新题目统计
        problem_data, _ = ProblemData.objects.get_or_create(problem=problem)
        problem_data.submission += 1
        problem_data.save()
        
        return _json_error(f'判题失败: {str(e)}', status=500)


@csrf_exempt
@jwt_required
@require_http_methods(['GET'])
def get_submission_detail(request, submission_id):
    """
    获取提交详情
    
    GET /api/problems/submissions/{submission_id}
    
    认证: 需要JWT Token
    
    返回: 提交详情
    {
        "success": true,
        "message": "获取成功",
        "data": {
            "submission_id": int,
            "problem_id": int,
            "problem_title": str,
            "user_id": int,
            "username": str,
            "code": str,
            "language": str,
            "status": int,
            "status_text": str,
            "cpu_time": int,
            "memory": int,
            "code_length": int,
            "submit_time": str,
            "result": dict
        }
    }
    """
    try:
        submission = Submission.objects.select_related('problem', 'user').get(submission_id=submission_id)
    except Submission.DoesNotExist:
        return _json_error('提交记录不存在', status=404)
    
    # 检查权限：只能查看自己的提交或管理员可以查看所有提交
    user = request.user
    if submission.user.id != user.id and (not user.permission or user.permission < 1):
        return _json_error('无权查看此提交记录', status=403)
    
    return _json_success('获取成功', data={
        'submission_id': submission.submission_id,
        'problem_id': submission.problem.problem_id,
        'problem_title': submission.problem.title,
        'user_id': submission.user.id,
        'username': submission.user.username,
        'code': submission.code,
        'language': submission.language,
        'status': submission.status,
        'status_text': submission.get_status_display(),
        'cpu_time': submission.cpu_time,
        'memory': submission.memory,
        'code_length': submission.code_length,
        'submit_time': submission.submit_time.isoformat(),
        'result': submission.result
    })


@csrf_exempt
@jwt_required
@require_http_methods(['GET'])
def list_submissions(request):
    """
    获取提交记录列表（支持分页、搜索、筛选）
    
    GET /api/problems/submissions/list
    
    查询参数：
    - page: 页码（默认1）
    - page_size: 每页数量（默认20）
    - problem_id: 题目ID筛选（可选）
    - user_id: 用户ID筛选（可选）
    - status: 状态筛选（可选，0=Accepted, -1=Wrong Answer, 1=Time Limit Exceeded, etc.）
    - language: 语言筛选（可选，cpp, java, python, javascript）
    
    认证: 需要JWT Token
    
    返回: 提交记录列表
    {
        "success": true,
        "message": "获取成功",
        "data": {
            "submissions": [
                {
                    "submission_id": int,
                    "problem_id": int,
                    "problem_title": str,
                    "user_id": int,
                    "username": str,
                    "language": str,
                    "status": int,
                    "status_text": str,
                    "cpu_time": int,
                    "memory": int,
                    "code_length": int,
                    "submit_time": str
                }
            ],
            "pagination": {
                "page": int,
                "page_size": int,
                "total": int,
                "total_pages": int,
                "has_next": bool,
                "has_previous": bool
            }
        }
    }
    """
    from django.core.paginator import Paginator
    from django.core.paginator import EmptyPage, PageNotAnInteger
    
    try:
        user = request.user
        
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
        
        # 构建查询 - 所有人都可以查看所有提交记录
        queryset = Submission.objects.select_related('problem', 'user').all()
        
        # 题目ID筛选
        if problem_id:
            try:
                problem_id = int(problem_id)
                queryset = queryset.filter(problem_id=problem_id)
            except (TypeError, ValueError):
                pass
        
        # 用户ID筛选（所有人都可以使用）
        if user_id:
            try:
                user_id = int(user_id)
                queryset = queryset.filter(user_id=user_id)
            except (TypeError, ValueError):
                pass
        
        # 测评ID筛选
        if submission_id:
            try:
                submission_id = int(submission_id)
                queryset = queryset.filter(submission_id=submission_id)
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
        except (EmptyPage, PageNotAnInteger):
            submissions_page = paginator.page(1)
            page = 1
        
        # 序列化提交记录
        submissions_data = []
        for submission in submissions_page:
            submissions_data.append({
                'submission_id': submission.submission_id,
                'problem_id': submission.problem.problem_id,
                'problem_title': submission.problem.title,
                'user_id': submission.user.id,
                'username': submission.user.username,
                'language': submission.language,
                'status': submission.status,
                'status_text': submission.get_status_display(),
                'cpu_time': submission.cpu_time,
                'memory': submission.memory,
                'code_length': submission.code_length,
                'submit_time': submission.submit_time.isoformat()
            })
        
        return _json_success('获取成功', data={
            'submissions': submissions_data,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': total_pages,
                'has_next': submissions_page.has_next() if total > 0 else False,
                'has_previous': submissions_page.has_previous() if total > 0 else False
            }
        })
    
    except Exception as e:
        import traceback
        print(f"获取提交记录失败: {str(e)}")
        print(traceback.format_exc())
        return _json_error(f'获取提交记录失败: {str(e)}', status=500)
