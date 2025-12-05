# -*- coding: utf-8 -*-

from django.db import IntegrityError, transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django.http import HttpResponse, JsonResponse
from django.core.files.uploadedfile import UploadedFile
from django.core.cache import cache

from problems.models import Problem, ProblemData
from users.views import _json_error, _json_success, _parse_request_body, jwt_required
from users.storage import get_s3_client, get_problem_testcase_path, upload_file_to_bucket
from django.conf import settings
import threading
import os
import zipfile
import tempfile
import shutil
from io import BytesIO
from uuid import uuid4


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
