#!/bin/bash
# 修复 Gunicorn 兼容性问题
# 使用方法: sudo bash fix-gunicorn.sh

set -e

echo "=========================================="
echo "修复 Gunicorn 兼容性问题"
echo "=========================================="
echo ""

PROJECT_DIR="/opt/huebRE"

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then 
    echo "请使用 sudo 运行此脚本"
    exit 1
fi

cd $PROJECT_DIR

echo "1. 激活虚拟环境并升级 Gunicorn..."
source venv/bin/activate
pip install --upgrade pip
pip install --upgrade gunicorn==21.2.0

echo ""
echo "2. 验证 Gunicorn 安装..."
gunicorn --version

echo ""
echo "3. 测试 Gunicorn 是否能正常启动..."
# 测试启动（后台运行，5秒后停止）
timeout 5 gunicorn --bind 127.0.0.1:8001 huebRE.wsgi:application || true

echo ""
echo "4. 重新加载 systemd 配置..."
systemctl daemon-reload

echo ""
echo "5. 启动 Gunicorn 服务..."
systemctl restart huebRE

echo ""
echo "6. 检查服务状态..."
sleep 2
systemctl status huebRE --no-pager | head -10

echo ""
echo "7. 检查端口监听..."
if netstat -tlnp 2>/dev/null | grep -q ":8000"; then
    echo "✓ 端口 8000 正在监听"
    netstat -tlnp | grep ":8000"
else
    echo "✗ 端口 8000 未监听，请检查日志:"
    echo "  sudo journalctl -u huebRE -n 20"
fi

echo ""
echo "=========================================="
echo "修复完成！"
echo "=========================================="
echo ""
echo "如果服务仍未启动，请查看日志："
echo "  sudo journalctl -u huebRE -f"

