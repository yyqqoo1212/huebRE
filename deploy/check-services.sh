#!/bin/bash
# 后端服务检查脚本
# 使用方法: bash check-services.sh

echo "=========================================="
echo "后端服务状态检查"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查 Gunicorn 服务
echo "1. 检查 Gunicorn 服务..."
if systemctl is-active --quiet huebRE; then
    echo -e "${GREEN}✓ Gunicorn 服务正在运行${NC}"
    systemctl status huebRE --no-pager -l | head -5
else
    echo -e "${RED}✗ Gunicorn 服务未运行${NC}"
    echo "  启动命令: sudo systemctl start huebRE"
fi
echo ""

# 检查 Nginx 服务
echo "2. 检查 Nginx 服务..."
if systemctl is-active --quiet nginx; then
    echo -e "${GREEN}✓ Nginx 服务正在运行${NC}"
    systemctl status nginx --no-pager -l | head -5
else
    echo -e "${RED}✗ Nginx 服务未运行${NC}"
    echo "  启动命令: sudo systemctl start nginx"
fi
echo ""

# 检查端口监听
echo "3. 检查端口监听..."
if netstat -tlnp 2>/dev/null | grep -q ":8000"; then
    echo -e "${GREEN}✓ 端口 8000 (Gunicorn) 正在监听${NC}"
    netstat -tlnp | grep ":8000"
else
    echo -e "${RED}✗ 端口 8000 (Gunicorn) 未监听${NC}"
fi

if netstat -tlnp 2>/dev/null | grep -q ":80"; then
    echo -e "${GREEN}✓ 端口 80 (Nginx) 正在监听${NC}"
    netstat -tlnp | grep ":80"
else
    echo -e "${RED}✗ 端口 80 (Nginx) 未监听${NC}"
fi
echo ""

# 检查防火墙
echo "4. 检查防火墙..."
if command -v ufw &> /dev/null; then
    ufw_status=$(ufw status | head -1)
    echo "防火墙状态: $ufw_status"
    if echo "$ufw_status" | grep -q "active"; then
        if ufw status | grep -q "80/tcp"; then
            echo -e "${GREEN}✓ 端口 80 已开放${NC}"
        else
            echo -e "${YELLOW}⚠ 端口 80 可能未开放${NC}"
            echo "  开放命令: sudo ufw allow 80/tcp"
        fi
    fi
else
    echo -e "${YELLOW}⚠ 未安装 ufw，请手动检查防火墙${NC}"
fi
echo ""

# 测试本地连接
echo "5. 测试本地连接..."
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/users/ | grep -q "200\|404\|405"; then
    echo -e "${GREEN}✓ Gunicorn 本地连接正常${NC}"
    curl -s http://127.0.0.1:8000/api/users/ | head -c 200
    echo ""
else
    echo -e "${RED}✗ Gunicorn 本地连接失败${NC}"
fi

if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/api/users/ | grep -q "200\|404\|405"; then
    echo -e "${GREEN}✓ Nginx 本地连接正常${NC}"
    curl -s http://127.0.0.1/api/users/ | head -c 200
    echo ""
else
    echo -e "${RED}✗ Nginx 本地连接失败${NC}"
fi
echo ""

# 检查最近日志
echo "6. 最近的错误日志..."
echo "Gunicorn 日志 (最近 10 行):"
journalctl -u huebRE -n 10 --no-pager | tail -5
echo ""
echo "Nginx 错误日志 (最近 10 行):"
tail -10 /var/log/nginx/huebRE_error.log 2>/dev/null || echo "  日志文件不存在"
echo ""

# 检查配置文件
echo "7. 检查配置文件..."
if [ -f "/opt/huebRE/.env" ]; then
    echo -e "${GREEN}✓ .env 文件存在${NC}"
    if grep -q "DJANGO_ALLOWED_HOSTS" /opt/huebRE/.env; then
        echo "  ALLOWED_HOSTS: $(grep DJANGO_ALLOWED_HOSTS /opt/huebRE/.env)"
    fi
else
    echo -e "${RED}✗ .env 文件不存在${NC}"
    echo "  请创建: cp /opt/huebRE/env.example /opt/huebRE/.env"
fi

if [ -f "/etc/nginx/sites-available/huebRE" ]; then
    echo -e "${GREEN}✓ Nginx 配置文件存在${NC}"
else
    echo -e "${RED}✗ Nginx 配置文件不存在${NC}"
fi
echo ""

echo "=========================================="
echo "检查完成"
echo "=========================================="

