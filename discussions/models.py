from django.db import models


class Discussion(models.Model):
    """
    讨论区主贴

    字段设计说明：
    - title: 标题
    - type: 讨论类型（题解/闲聊/求解/分享）
    - content: Markdown 原文
    - author: 关联到自定义用户模型
    - comments_count: 评论数（后续实现评论功能时更新）
    - likes_count: 点赞数（后续实现点赞功能时更新）
    - created_at/updated_at: 创建 & 更新时间
    """

    TYPE_SOLUTION = 'solution'
    TYPE_CHAT = 'chat'
    TYPE_HELP = 'help'
    TYPE_SHARE = 'share'

    TYPE_CHOICES = [
        (TYPE_SOLUTION, '题解'),
        (TYPE_CHAT, '闲聊'),
        (TYPE_HELP, '求解'),
        (TYPE_SHARE, '分享'),
    ]

    title = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_CHAT)
    content = models.TextField()

    author = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='discussions',
    )

    comments_count = models.PositiveIntegerField(default=0)
    likes_count = models.PositiveIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)
    is_pinned = models.BooleanField(default=False, verbose_name='是否置顶')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_pinned', '-created_at']

    def __str__(self) -> str:
        return f'{self.title} ({self.author.username})'


