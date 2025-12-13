# JudgeServer API 参数说明

本文档详细说明发送给判题服务器的请求参数和返回的结果参数。

## 一、请求参数（发送给判题服务器）

### 1. `/judge` 接口 - 判题接口

#### 请求头（Headers）

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `X-Judge-Server-Token` | string | 是 | Token 的 SHA256 哈希值（32位十六进制字符串） |
| `Content-Type` | string | 是 | 固定值：`application/json` |

#### 请求体（Body）参数

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| `src` | string | 是 | 源代码内容 | `"#include <stdio.h>..."` |
| `language_config` | object | 是 | 编程语言配置（见下方详细说明） | `{ "compile": {...}, "run": {...} }` |
| `max_cpu_time` | integer | 是 | 最大 CPU 时间限制（毫秒） | `1000` |
| `max_memory` | integer | 是 | 最大内存限制（字节） | `134217728` (128MB) |
| `test_case_id` | string | 否* | 测试用例 ID（使用预定义的测试用例） | `"normal"` |
| `test_case` | array | 否* | 动态测试用例数组（见下方说明） | `[{"input": "...", "output": "..."}]` |
| `output` | boolean | 否 | 是否返回程序输出内容 | `true` / `false` |
| `spj_version` | string | 否 | 特殊判题程序版本号 | `"2"` |
| `spj_config` | object | 否 | 特殊判题程序运行配置 | `{ "exe_name": "...", "command": "..." }` |
| `spj_compile_config` | object | 否 | 特殊判题程序编译配置 | `{ "src_name": "...", "compile_command": "..." }` |
| `spj_src` | string | 否 | 特殊判题程序源代码 | `"#include <stdio.h>..."` |
| `io_mode` | object | 否 | 输入输出模式（默认标准输入输出） | `{"io_mode": "Standard IO"}` |

**注意**：`test_case_id` 和 `test_case` 必须且只能提供一个。

#### `language_config` 详细说明

##### 需要编译的语言（C/C++/Java/Go/Python）

```json
{
  "compile": {
    "src_name": "main.c",              // 源文件名
    "exe_name": "main",                 // 编译后的可执行文件名
    "max_cpu_time": 3000,               // 编译最大 CPU 时间（毫秒）
    "max_real_time": 5000,              // 编译最大实际时间（毫秒）
    "max_memory": 134217728,            // 编译最大内存（字节）
    "compile_command": "/usr/bin/gcc ..."  // 编译命令（支持 {src_path} 和 {exe_path} 占位符）
  },
  "run": {
    "command": "{exe_path}",            // 运行命令（支持 {exe_path}, {exe_dir}, {max_memory} 占位符）
    "seccomp_rule": "c_cpp",            // seccomp 安全规则名称
    "env": ["LANG=en_US.UTF-8", ...]   // 环境变量数组
  }
}
```

##### 解释型语言（PHP/JavaScript）

```json
{
  "run": {
    "exe_name": "solution.php",         // 源代码文件名
    "command": "/usr/bin/php {exe_path}",  // 运行命令
    "seccomp_rule": "",                 // 空字符串表示不使用 seccomp
    "env": ["LANG=en_US.UTF-8", ...],   // 环境变量数组
    "memory_limit_check_only": 1        // 仅检查内存限制（某些语言需要）
  }
}
```

#### `test_case` 数组格式

```json
[
  {
    "input": "1 2\n",        // 测试输入数据
    "output": "3"            // 期望输出（用于验证，如果不需要验证可留空）
  },
  {
    "input": "2 3\n",
    "output": "5"
  }
]
```

### 2. `/ping` 接口 - 测试连接

#### 请求头
同 `/judge` 接口

#### 请求体
空对象 `{}` 或不提供

### 3. `/compile_spj` 接口 - 编译特殊判题程序

#### 请求头
同 `/judge` 接口

#### 请求体参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `src` | string | 是 | 特殊判题程序源代码 |
| `spj_version` | string | 是 | 版本号 |
| `spj_compile_config` | object | 是 | 编译配置（同 `language_config.compile`） |

---

## 二、返回结果参数（判题服务器返回）

### 响应格式

所有接口返回统一的 JSON 格式：

```json
{
  "err": null,        // 错误类型，null 表示成功
  "data": {...}       // 数据内容（根据接口不同而不同）
}
```

### 错误响应

当 `err` 不为 `null` 时，表示发生错误：

| err 值 | 说明 |
|--------|------|
| `TokenVerificationFailed` | Token 验证失败 |
| `CompileError` | 编译错误 |
| `SPJCompileError` | 特殊判题程序编译错误 |
| `JudgeClientError` | 判题客户端错误 |
| `InvalidRequest` | 无效请求 |

### `/judge` 接口返回结果

#### 成功时 `data` 格式

`data` 是一个数组，每个元素对应一个测试用例的结果：

```json
[
  {
    "cpu_time": 0,              // CPU 时间（毫秒）
    "real_time": 1,             // 实际时间（毫秒）
    "memory": 1441792,           // 内存使用（字节）
    "signal": 0,                // 信号编号（0 表示无信号）
    "exit_code": 0,             // 程序退出码
    "error": 0,                  // 错误类型（见下方错误类型表）
    "result": 0,                // 判题结果（见下方结果代码表）
    "test_case": "1",           // 测试用例编号
    "output_md5": "eccbc87e...", // 输出内容的 MD5 哈希值（如果设置了 output）
    "output": "3\n"             // 程序输出内容（如果设置了 output=true）
  }
]
```

#### `result` 结果代码表

| 代码 | 常量名 | 说明 |
|------|--------|------|
| `0` | `RESULT_SUCCESS` | 成功（程序正常运行并退出） |
| `-1` | `RESULT_WRONG_ANSWER` | 答案错误（输出不匹配） |
| `1` | `RESULT_CPU_TIME_LIMIT_EXCEEDED` | CPU 时间超限 |
| `2` | `RESULT_REAL_TIME_LIMIT_EXCEEDED` | 实际时间超限 |
| `3` | `RESULT_MEMORY_LIMIT_EXCEEDED` | 内存超限 |
| `4` | `RESULT_RUNTIME_ERROR` | 运行时错误 |
| `5` | `RESULT_SYSTEM_ERROR` | 系统错误 |

#### `error` 错误类型表

| 代码 | 说明 |
|------|------|
| `0` | 无错误 |
| `1` | 权限错误 |
| `2` | 系统调用错误 |
| `3` | 文件操作错误 |
| `4` | 信号错误 |
| `5` | 其他错误 |
| `6` | 特殊判题程序错误（SPJ_ERROR） |

#### `signal` 信号编号

常见的信号编号：
- `0` - 无信号
- `11` - SIGSEGV（段错误）
- `9` - SIGKILL（被强制终止）
- `14` - SIGALRM（超时）

### `/ping` 接口返回结果

```json
{
  "err": null,
  "data": {
    "action": "pong",
    "hostname": "judge_server",
    "cpu": 10.5,                    // CPU 使用率（%）
    "cpu_core": 4,                  // CPU 核心数
    "memory": 45.2,                 // 内存使用率（%）
    "judger_version": "1.0.0"       // Judger 版本号
  }
}
```

### `/compile_spj` 接口返回结果

```json
{
  "err": null,
  "data": "success"
}
```

---

## 三、完整请求示例

### 示例 1：C 语言判题（使用预定义测试用例）

```bash
curl -X POST http://101.42.172.229:12358/judge \
  -H "X-Judge-Server-Token: <TOKEN_HASH>" \
  -H "Content-Type: application/json" \
  -d '{
    "src": "#include <stdio.h>\nint main(){\n    int a, b;\n    scanf(\"%d%d\", &a, &b);\n    printf(\"%d\\n\", a+b);\n    return 0;\n}",
    "language_config": {
      "compile": {
        "src_name": "main.c",
        "exe_name": "main",
        "max_cpu_time": 3000,
        "max_real_time": 5000,
        "max_memory": 134217728,
        "compile_command": "/usr/bin/gcc -DONLINE_JUDGE -O2 -w -fmax-errors=3 -std=c99 {src_path} -lm -o {exe_path}"
      },
      "run": {
        "command": "{exe_path}",
        "seccomp_rule": "c_cpp",
        "env": ["LANG=en_US.UTF-8", "LANGUAGE=en_US:en", "LC_ALL=en_US.UTF-8"]
      }
    },
    "max_cpu_time": 1000,
    "max_memory": 134217728,
    "test_case_id": "normal",
    "output": true
  }'
```

### 示例 2：Python 3 判题（使用动态测试用例）

```bash
curl -X POST http://101.42.172.229:12358/judge \
  -H "X-Judge-Server-Token: <TOKEN_HASH>" \
  -H "Content-Type: application/json" \
  -d '{
    "src": "s = input()\ns1 = s.split(\" \")\nprint(int(s1[0]) + int(s1[1]))",
    "language_config": {
      "compile": {
        "src_name": "solution.py",
        "exe_name": "__pycache__/solution.cpython-36.pyc",
        "max_cpu_time": 3000,
        "max_real_time": 5000,
        "max_memory": 134217728,
        "compile_command": "/usr/bin/python3 -m py_compile {src_path}"
      },
      "run": {
        "command": "/usr/bin/python3 {exe_path}",
        "seccomp_rule": "general",
        "env": ["PYTHONIOENCODING=UTF-8", "LANG=en_US.UTF-8", "LANGUAGE=en_US:en", "LC_ALL=en_US.UTF-8"]
      }
    },
    "max_cpu_time": 1000,
    "max_memory": 134217728,
    "test_case": [
      {"input": "1 2\n", "output": "3"},
      {"input": "5 7\n", "output": "12"}
    ],
    "output": true
  }'
```

### 示例 3：测试连接

```bash
TOKEN="your_token"
TOKEN_HASH=$(echo -n "$TOKEN" | sha256sum | cut -d' ' -f1)

curl -X POST http://101.42.172.229:12358/ping \
  -H "X-Judge-Server-Token: $TOKEN_HASH" \
  -H "Content-Type: application/json"
```

---

## 四、常见问题

### Q1: Token 如何计算？

Token 需要进行 SHA256 哈希计算：

```bash
# Linux/Mac
echo -n "your_token" | sha256sum | cut -d' ' -f1

# Python
import hashlib
hashlib.sha256("your_token".encode("utf-8")).hexdigest()
```

### Q2: 如何判断判题结果？

- `result == 0`：程序运行成功，输出正确（Accepted）
- `result == -1`：程序运行成功，但输出错误（Wrong Answer）
- `result > 0`：程序运行失败（超时、内存超限、运行时错误等）

### Q3: 内存和时间单位是什么？

- 时间：毫秒（ms）
- 内存：字节（bytes）
  - 1 MB = 1024 * 1024 = 1048576 bytes
  - 128 MB = 134217728 bytes

### Q4: 如何获取程序输出？

在请求中设置 `"output": true`，返回结果的 `output` 字段会包含程序的标准输出内容。

### Q5: 支持哪些编程语言？

- C（需要编译）
- C++（需要编译）
- Java（需要编译）
- Python 2（需要编译）
- Python 3（需要编译）
- Go（需要编译）
- PHP（解释型）
- JavaScript/Node.js（解释型）

每种语言需要对应的 `language_config` 配置。

---

## 五、参考资源

- 项目地址：https://github.com/QingdaoU/JudgeServer
- Judger 库：https://github.com/QingdaoU/Judger
- 客户端示例：查看 `client/` 目录下的各种语言客户端

