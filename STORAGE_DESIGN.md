# 文件存储设计文档

## 存储方案

**推荐方案：同一个bucket + 不同文件夹**

使用单个bucket `onlinejudge`，通过文件夹结构组织不同类型的文件。

### 优势
- ✅ 管理简单，只需维护一个bucket
- ✅ 权限配置统一
- ✅ 成本更低（MinIO通常不按bucket数量收费）
- ✅ 备份和迁移更方便
- ✅ 结构清晰，通过文件夹即可区分

## Minio文件夹结构

```
onlinejudge/
├── avatars/                    # 用户头像
│   └── {user_id}/{filename}
│   └── 示例: avatars/1/avatar.jpg
│
├── problems/                   # 题目相关
│   └── {problem_id}/
│       ├── testcases/         # 测试用例（输入输出文件）
│       │   ├── 1.in
│       │   ├── 1.out
│       │   ├── 2.in
│       │   └── ...
│       └── images/            # 题目图片
│           └── {filename}
│   └── 示例: problems/1001/testcases/1.in
│   └── 示例: problems/1001/images/problem_diagram.png
│
├── courses/                    # 课程相关
│   └── {course_id}/
│       └── images/            # 课程图片
│           └── {filename}
│   └── 示例: courses/10/images/course_cover.jpg
│
└── discussions/               # 讨论区
    └── {discussion_id}/
        └── images/            # 讨论区图片
            └── {filename}
    └── 示例: discussions/50/images/screenshot.png
```

## API使用示例

### 上传用户头像

```bash
POST /api/files/upload
Content-Type: multipart/form-data

file: [头像文件]
object_key: avatars/1/avatar_uuid123.jpg
```

### 上传题目测试用例

```bash
POST /api/files/upload
Content-Type: multipart/form-data

file: [1.in文件]
object_key: problems/1001/testcases/1.in
```

### 获取文件URL

```bash
GET /api/files/get?object_key=avatars/1/avatar.jpg
```

## 注意事项

1. **文件名唯一性**：建议使用 `generate_unique_filename()` 生成唯一文件名，避免文件名冲突
2. **路径规范**：使用提供的路径生成函数，确保路径格式统一
3. **权限控制**：根据业务需求，可以在API层面添加权限验证
4. **文件清理**：删除用户/题目/课程时，记得清理相关文件
5. **备份策略**：定期备份整个bucket，确保数据安全

