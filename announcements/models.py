from django.db import models

from users.models import User


class SystemAnnouncement(models.Model):
    """
    系统公告（用于首页公告栏 & 后台公告管理）
    """

    title = models.CharField(max_length=200, verbose_name='公告标题')
    content = models.TextField(verbose_name='公告内容')
    is_important = models.BooleanField(default=False, verbose_name='是否置顶')
    publisher = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='system_announcements',
        verbose_name='发布人',
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'system_announcement'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.title

