# huebRE 后端部署指南

## 部署架构

- **Web 服务器**: Nginx（反向代理）
- **WSGI 服务器**: Gunicorn
- **应用服务器**: Django
- **数据库**: MySQL
- **对象存储**: MinIO

## 1. 项目文件位置

推荐将项目放在 `/opt/huebRE`，这是 Linux 系统中存放第三方软件的标准位置。

```bash
sudo mkdir -p /opt/huebRE
sudo chown $USER:$USER /opt/huebRE
```

## 2. 上传项目文件

将项目文件上传到服务器：

```bash
# 方法1: 使用 scp（从本机执行）
scp -r huebRE/ user@101.42.172.229:/opt/

# 方法2: 使用 git（推荐）
cd /opt
sudo git clone <your-repo-url> huebRE
sudo chown -R $USER:$USER /opt/huebRE
```

## 3. 安装系统依赖

```bash
# 更新系统
sudo apt update
sudo apt upgrade -y

# 安装 Python 和 pip
sudo apt install -y python3 python3-pip python3-venv

# 安装 MySQL 客户端库（如果需要）
sudo apt install -y default-libmysqlclient-dev pkg-config

# 安装 Nginx
sudo apt install -y nginx

# 安装其他工具
sudo apt install -y git curl
```

## 4. 创建 Python 虚拟环境

```bash
cd /opt/huebRE
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 5. 配置环境变量

```bash
cd /opt/huebRE
cp env.example .env
nano .env  # 编辑配置文件，设置正确的值
```

确保 `.env` 文件包含：
- `DJANGO_DEBUG=False`
- `DJANGO_ALLOWED_HOSTS=101.42.172.229,localhost,127.0.0.1`
- 正确的数据库和 MinIO 配置

## 6. 初始化数据库

```bash
cd /opt/huebRE
source venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput  # 如果有静态文件
```

## 7. 配置 Gunicorn

### 7.1 创建 systemd 服务文件

```bash
sudo cp deploy/gunicorn.service /etc/systemd/system/huebRE.service
sudo systemctl daemon-reload
```

### 7.2 创建运行目录

```bash
sudo mkdir -p /var/run/gunicorn
sudo chown www-data:www-data /var/run/gunicorn
```

### 7.3 启动 Gunicorn 服务

```bash
sudo systemctl start huebRE
sudo systemctl enable huebRE  # 开机自启
sudo systemctl status huebRE  # 查看状态
```

## 8. 配置 Nginx

### 8.1 复制配置文件

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/huebRE
```

### 8.2 创建软链接

```bash
sudo ln -s /etc/nginx/sites-available/huebRE /etc/nginx/sites-enabled/
```

### 8.3 测试配置

```bash
sudo nginx -t
```

### 8.4 重启 Nginx

```bash
sudo systemctl restart nginx
sudo systemctl enable nginx  # 开机自启
```

## 9. 配置防火墙

```bash
# 允许 HTTP 和 HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 如果使用其他端口，例如 8000（不推荐直接暴露）
# sudo ufw allow 8000/tcp
```

## 10. 验证部署

```bash
# 检查 Gunicorn 状态
sudo systemctl status huebRE

# 检查 Nginx 状态
sudo systemctl status nginx

# 查看日志
sudo journalctl -u huebRE -f
sudo tail -f /var/log/nginx/huebRE_access.log
sudo tail -f /var/log/nginx/huebRE_error.log

# 测试 API
curl http://101.42.172.229/api/users/
```

## 11. 常用管理命令

### Gunicorn 服务管理

```bash
# 启动
sudo systemctl start huebRE

# 停止
sudo systemctl stop huebRE

# 重启
sudo systemctl restart huebRE

# 查看状态
sudo systemctl status huebRE

# 查看日志
sudo journalctl -u huebRE -f
```

### Nginx 管理

```bash
# 重启
sudo systemctl restart nginx

# 重新加载配置（不中断服务）
sudo systemctl reload nginx

# 测试配置
sudo nginx -t
```

### 更新代码

```bash
cd /opt/huebRE
source venv/bin/activate

# 拉取最新代码
git pull

# 安装新依赖
pip install -r requirements.txt

# 运行数据库迁移
python manage.py migrate

# 收集静态文件（如果有）
python manage.py collectstatic --noinput

# 重启服务
sudo systemctl restart huebRE
```

## 12. 安全建议

1. **修改默认密码**: 确保 MySQL 和 MinIO 使用强密码
2. **配置 SSL**: 使用 Let's Encrypt 配置 HTTPS
3. **定期备份**: 设置数据库和文件的自动备份
4. **监控日志**: 定期检查错误日志
5. **更新系统**: 定期更新系统和依赖包

## 13. 故障排查

### Gunicorn 无法启动

```bash
# 查看详细错误
sudo journalctl -u huebRE -n 50

# 检查权限
ls -la /opt/huebRE
ls -la /opt/huebRE/venv/bin/gunicorn

# 手动测试
cd /opt/huebRE
source venv/bin/activate
gunicorn huebRE.wsgi:application --bind 127.0.0.1:8000
```

### Nginx 502 错误

```bash
# 检查 Gunicorn 是否运行
sudo systemctl status huebRE

# 检查端口是否监听
sudo netstat -tlnp | grep 8000

# 检查 Nginx 错误日志
sudo tail -f /var/log/nginx/huebRE_error.log
```

### 数据库连接问题

```bash
# 测试 MySQL 连接
mysql -h localhost -u root -p

# 检查 Django 数据库配置
cd /opt/huebRE
source venv/bin/activate
python manage.py dbshell
```

## 14. 性能优化

1. **调整 Gunicorn workers**: 根据 CPU 核心数调整 `workers` 数量
2. **启用 Nginx 缓存**: 对静态资源启用缓存
3. **数据库优化**: 添加适当的索引
4. **使用 CDN**: 对静态文件使用 CDN
