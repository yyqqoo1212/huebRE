# 题目列表查询性能优化指南

## 📊 当前性能评估

### 查询分析
- **查询方式**：使用 `select_related('problem')` 避免 N+1 查询 ✅
- **分页**：每页默认 20 条，只查询当前页数据 ✅
- **查询频率**：每次访问都查询数据库 ⚠️

### 压力评估

| 题目数量 | 并发用户 | 压力等级 | 建议 |
|---------|---------|---------|------|
| < 1,000 | < 100 | 🟢 很小 | 无需优化 |
| 1,000 - 10,000 | 100 - 500 | 🟡 中等 | 添加索引 + 缓存 |
| > 10,000 | > 500 | 🔴 较大 | 必须优化 |

## 🚀 优化方案

### 方案 1：数据库索引优化（已实施）✅

已在 `models.py` 中添加索引：

```python
# ProblemData 模型
indexes = [
    models.Index(fields=['auth', 'level']),  # 复合索引，优化筛选查询
    models.Index(fields=['title']),          # 优化标题搜索
]

# Problem 模型
indexes = [
    models.Index(fields=['auth']),           # 优化权限筛选
    models.Index(fields=['problem_id']),     # 优化主键查询
]
```

**应用索引**：
```bash
cd huebRE
python manage.py makemigrations problems
python manage.py migrate
```

**性能提升**：查询速度提升 50-90%

### 方案 2：Redis 缓存（可选，推荐）

#### 2.1 安装 Redis
```bash
# Windows (使用 WSL 或 Docker)
# 或使用 Redis for Windows

# Linux
sudo apt-get install redis-server
```

#### 2.2 安装 Django Redis
```bash
pip install django-redis
```

#### 2.3 配置 settings.py
```python
# 添加到 INSTALLED_APPS
INSTALLED_APPS = [
    # ...
    'django_redis',
]

# 缓存配置
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'KEY_PREFIX': 'hueb',
        'TIMEOUT': 300,  # 默认缓存 5 分钟
    }
}
```

#### 2.4 修改 views.py（添加缓存）
```python
from django.core.cache import cache
from django.views.decorators.cache import cache_page

# 方式1：使用装饰器（简单）
@cache_page(60 * 5)  # 缓存 5 分钟
def list_problems(request):
    # ... 现有代码 ...

# 方式2：手动缓存（更灵活）
def list_problems(request):
    # 构建缓存键
    cache_key = f'problem_list:page_{page}:size_{page_size}:search_{search}:level_{level}'
    
    # 尝试从缓存获取
    cached_result = cache.get(cache_key)
    if cached_result:
        return JsonResponse(cached_result)
    
    # 查询数据库
    # ... 现有查询逻辑 ...
    
    # 设置缓存（有搜索时缓存时间短）
    cache_timeout = 60 if (search or level) else 300
    cache.set(cache_key, result, cache_timeout)
    
    return JsonResponse(result)
```

**性能提升**：减少 80-95% 的数据库查询

### 方案 3：查询优化（已实施）✅

- ✅ 使用 `select_related()` 避免 N+1 查询
- ✅ 使用分页限制查询数量
- ✅ 限制每页最大数量（100 条）

### 方案 4：只查询需要的字段（可选）

```python
queryset = ProblemData.objects.select_related('problem').filter(
    auth=Problem.PUBLIC
).only(
    'problem__problem_id',
    'title',
    'level',
    'submission',
    'ac',
    'tag',
    'score'
)
```

**性能提升**：减少 20-30% 的数据传输

## 📈 性能测试

### 测试场景
- 10,000 条题目数据
- 100 并发用户
- 每页 20 条

### 测试结果（预估）

| 方案 | 平均响应时间 | 数据库查询次数/秒 | CPU 使用率 |
|------|------------|-----------------|-----------|
| 无优化 | 200-500ms | 100 | 60% |
| 仅索引 | 50-150ms | 100 | 40% |
| 索引 + 缓存 | 10-30ms | 5-10 | 20% |

## 🎯 推荐方案

### 当前阶段（题目 < 1000）
- ✅ 已添加数据库索引
- ⏸️ 暂不需要缓存

### 发展阶段（题目 1000-10000）
- ✅ 数据库索引
- ✅ 添加 Redis 缓存（5 分钟）

### 成熟阶段（题目 > 10000）
- ✅ 数据库索引
- ✅ Redis 缓存
- ✅ 考虑 CDN 缓存静态内容
- ✅ 考虑读写分离

## ⚠️ 注意事项

1. **缓存失效**：当题目数据更新时，需要清除相关缓存
2. **缓存键设计**：确保不同查询参数使用不同的缓存键
3. **监控**：定期监控数据库查询性能和缓存命中率

## 🔧 缓存清除

```python
# 清除所有题目列表缓存
from django.core.cache import cache
cache.delete_pattern('problem_list:*')

# 清除特定题目缓存
cache.delete(f'problem_detail:{problem_id}')
```

