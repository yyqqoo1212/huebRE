# huebOnlineJudgeRE

### 接口总览

| 序号 | 接口路径             | 请求方法  | 功能     |  是否需要认证  |
|------|---------------------|----------|----------|---------------|
| 1    | /api/users/register | POST     | 用户注册  | 否            |
| 2    | /api/users/login    | POST     | 用户登录  | 否            |


### 数据表设计
#### user 存储用户
|字段|类型|说明|
|----|----|----|
|id|BIGINT PRIMARY KEY|主键|
|username|VARCHAR(50) UNIQUE|用户名|
|password_hash| VARCHAR(255) |哈希后的密码|
|email| VARCHAR(100) UNIQUE| 邮箱|
|motto| VARCHAR(255)| 座右铭|
|avatar_url |VARCHAR(255)| 头像 URL（文件/OSS）|
|total_submissions| INT |总提交数（冗余字段，加速统计）|
|accepted_submissions| INT |通过题目总数|
|created_at |DATETIME| 注册时间|
|permission |INT| 权限|

#### problem主表
|字段|类型|说明|
|----|----|----|
|id|BIGINT PK AUTO_INCREMENT|唯一标识,用于：列表跳转、后台编辑、接口查询、提交记录关联|
|title|VARCHAR(255) NOT NULL|题目标题|
|difficulty|TINYINT NOT NULL|难度字段（1=简单，2=中等，3=困难）|
|submissions|INT DEFAULT 0|题目被用户提交的总次数|
|accepted_count|INT DEFAULT 0|通过次数|
|created_at|DATETIME DEFAULT CURRENT_TIMESTAMP|创建时间|
|updated_at|DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP|更新时间
|status|TINYINT DEFAULT 1|题目是否上线|

#### problem_contents大字段表
|字段|类型|说明|
|----|----|----|
|problem_id|BIGINT PRIMARY KEY|关联题目id|
|content|LONGTEXT NOT NULL|题目内容|
|input_description|LONGTEXT|输入描述|
|output_description|LONGTEXT|输出描述|
|explain|LONGTEXT|解释说明|
|examples|LONGTEXT|

#### tags表(所有标签)
|字段|类型|说明|
|----|----|----|
|id|INT PRIMARY KEY AUTO_INCREMENT|标签唯一id|
|name|VARCHAR(64) UNIQUE|标签名|

#### problem_tags表 (题目与标签的关联表-一对多)
|字段|类型|说明|
|----|----|----|
|problem_id|BIGINT NOT NULL|题目ID|
|tag_id|INT NOT NULL|标签ID|
PRIMARY KEY (problem_id, tag_id),
FOREIGN KEY (problem_id) REFERENCES problems(id),
FOREIGN KEY (tag_id) REFERENCES tags(id)

#### problem_tests表 测试数据表
|字段|类型|说明|
|----|----|----|
|id|BIGINT PRIMARY KEY AUTO_INCREMENT|
|problem_id|BIGINT NOT NULL|
|input_path|VARCHAR(255) NOT NULL|输入文件存放位置|
|output_path|VARCHAR(255) NOT NULL|输出文件存放位置|
|score|INT DEFAULT 0|分数，ACM模式=0；OI模式可以用得上|
|is_sample|TINYINT DEFAULT 0|是否为样例（可让前端展示）
|group_id|INT DEFAULT 0|分组评测（如多个测试点一组）
|created_at|DATETIME DEFAULT CURRENT_TIMESTAMP|
|FOREIGN KEY (problem_id) REFERENCES problems(id)|