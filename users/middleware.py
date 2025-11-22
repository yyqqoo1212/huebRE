"""数据库自动恢复中间件"""
import logging
from django.db import OperationalError
from django.conf import settings

logger = logging.getLogger(__name__)


class DatabaseAutoRecoveryMiddleware:
    """自动恢复数据库和表的中间件"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self._checked = False  # 避免每次请求都检查
        
    def __call__(self, request):
        # 只在第一次请求时检查，避免性能问题
        if not self._checked:
            try:
                from django.db import connection
                connection.ensure_connection()
                self._checked = True
            except OperationalError:
                # 数据库连接失败，尝试恢复
                try:
                    if hasattr(settings, 'ensure_database_and_tables'):
                        settings.ensure_database_and_tables()
                        self._checked = True
                except Exception as exc:
                    logger.error(f"数据库自动恢复失败: {exc}")
        
        response = self.get_response(request)
        return response

