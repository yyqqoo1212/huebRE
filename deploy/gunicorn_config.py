# Gunicorn 配置文件
# 可以通过命令行参数 --config gunicorn_config.py 使用

import multiprocessing
import os

# 服务器套接字
bind = "127.0.0.1:8000"
backlog = 2048

# 工作进程
workers = multiprocessing.cpu_count() * 2 + 1  # 推荐公式
worker_class = "sync"
worker_connections = 1000
timeout = 60
keepalive = 5

# 日志
accesslog = "-"  # 输出到 stdout
errorlog = "-"   # 输出到 stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 进程命名
proc_name = "huebRE"

# 服务器机制
daemon = False
pidfile = "/var/run/gunicorn/huebRE.pid"
umask = 0
user = None  # 由 systemd 设置
group = None  # 由 systemd 设置
tmp_upload_dir = None

# SSL（如果使用 HTTPS）
# keyfile = None
# certfile = None