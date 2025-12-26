# -*- coding: utf-8 -*-

from django.db import models
from django.utils import timezone


class Contest(models.Model):
    """
    比赛基础信息表
    """
    contest_id = models.AutoField(primary_key=True, verbose_name='比赛ID')
    contest_name = models.CharField(max_length=255, verbose_name='比赛名称')
    description = models.TextField(blank=True, null=True, verbose_name='比赛描述')
    creator_id = models.IntegerField(verbose_name='创建者ID')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'contest'
        ordering = ['-create_time']
        verbose_name = '比赛'
        verbose_name_plural = '比赛'
        indexes = [
            models.Index(fields=['creator_id'], name='contest_creator_id_idx'),
            models.Index(fields=['create_time'], name='contest_create_time_idx'),
        ]

    def __str__(self):
        return f'{self.contest_id} - {self.contest_name}'


class ContestTimeConfig(models.Model):
    """
    比赛时间配置表
    """
    STATUS_UPCOMING = '即将开始'
    STATUS_ACTIVE = '进行中'
    STATUS_ENDED = '已结束'

    STATUS_CHOICES = (
        (STATUS_UPCOMING, '即将开始'),
        (STATUS_ACTIVE, '进行中'),
        (STATUS_ENDED, '已结束'),
    )

    id = models.AutoField(primary_key=True, verbose_name='主键')
    contest = models.OneToOneField(
        Contest,
        on_delete=models.CASCADE,
        related_name='time_config',
        verbose_name='比赛',
        db_column='contest_id'
    )
    start_time = models.DateTimeField(verbose_name='比赛开始时间')
    end_time = models.DateTimeField(verbose_name='比赛结束时间')
    duration = models.PositiveIntegerField(verbose_name='比赛持续时间(分钟)')
    register_start_time = models.DateTimeField(null=True, blank=True, verbose_name='报名开始时间')
    register_end_time = models.DateTimeField(null=True, blank=True, verbose_name='报名结束时间')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_UPCOMING,
        verbose_name='比赛当前状态'
    )
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'contest_time_config'
        verbose_name = '比赛时间配置'
        verbose_name_plural = '比赛时间配置'
        indexes = [
            models.Index(fields=['start_time'], name='contest_time_start_time_idx'),
            models.Index(fields=['status'], name='contest_time_status_idx'),
        ]

    def __str__(self):
        return f'{self.contest.contest_id} - {self.status}'


class ContestRuleConfig(models.Model):
    """
    比赛规则配置表
    """
    CONTEST_TYPE_ACM = 'ACM'
    CONTEST_TYPE_IOI = 'IOI'
    CONTEST_TYPE_OI = 'OI'

    CONTEST_TYPE_CHOICES = (
        (CONTEST_TYPE_ACM, 'ACM'),
        (CONTEST_TYPE_IOI, 'IOI'),
        (CONTEST_TYPE_OI, 'OI'),
    )

    CONTEST_MODE_PUBLIC = '公开赛'
    CONTEST_MODE_PRIVATE = '私有赛'

    CONTEST_MODE_CHOICES = (
        (CONTEST_MODE_PUBLIC, '公开赛'),
        (CONTEST_MODE_PRIVATE, '私有赛'),
    )

    id = models.AutoField(primary_key=True, verbose_name='主键')
    contest = models.OneToOneField(
        Contest,
        on_delete=models.CASCADE,
        related_name='rule_config',
        verbose_name='比赛',
        db_column='contest_id'
    )
    contest_type = models.CharField(
        max_length=10,
        choices=CONTEST_TYPE_CHOICES,
        default=CONTEST_TYPE_ACM,
        verbose_name='赛制'
    )
    contest_mode = models.CharField(
        max_length=20,
        choices=CONTEST_MODE_CHOICES,
        default=CONTEST_MODE_PUBLIC,
        verbose_name='赛种'
    )
    password = models.CharField(max_length=255, null=True, blank=True, verbose_name='比赛密码(加密存储)')
    penalty_time = models.PositiveIntegerField(default=20, verbose_name='罚时(分钟，默认20)')
    language_limit = models.JSONField(null=True, blank=True, verbose_name='语言限制(JSON数组)')
    allow_submit_after_end = models.BooleanField(default=False, verbose_name='结束后是否可提交')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'contest_rule_config'
        verbose_name = '比赛规则配置'
        verbose_name_plural = '比赛规则配置'
        indexes = [
            models.Index(fields=['contest_type'], name='contest_rule_type_idx'),
            models.Index(fields=['contest_mode'], name='contest_rule_mode_idx'),
        ]

    def __str__(self):
        return f'{self.contest.contest_id} - {self.contest_type}'


class ContestPermissionConfig(models.Model):
    """
    比赛权限配置表
    """
    id = models.AutoField(primary_key=True, verbose_name='主键')
    contest = models.OneToOneField(
        Contest,
        on_delete=models.CASCADE,
        related_name='permission_config',
        verbose_name='比赛',
        db_column='contest_id'
    )
    visibility = models.BooleanField(default=True, verbose_name='比赛是否可见')
    show_rank = models.BooleanField(default=True, verbose_name='是否显示排行榜')
    show_others_code = models.BooleanField(default=False, verbose_name='是否可查看他人代码')
    show_testcase = models.BooleanField(default=False, verbose_name='是否显示测试用例')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'contest_permission_config'
        verbose_name = '比赛权限配置'
        verbose_name_plural = '比赛权限配置'
        indexes = [
            models.Index(fields=['visibility'], name='contest_perm_visibility_idx'),
        ]

    def __str__(self):
        return f'{self.contest.contest_id} - visibility:{self.visibility}'


class ContestStatistics(models.Model):
    """
    比赛统计信息表
    """
    id = models.AutoField(primary_key=True, verbose_name='主键')
    contest = models.OneToOneField(
        Contest,
        on_delete=models.CASCADE,
        related_name='statistics',
        verbose_name='比赛',
        db_column='contest_id'
    )
    participant_count = models.PositiveIntegerField(default=0, verbose_name='参赛人数')
    registration_count = models.PositiveIntegerField(default=0, verbose_name='报名人数')
    submission_count = models.PositiveIntegerField(default=0, verbose_name='总提交次数')
    problem_count = models.PositiveIntegerField(default=0, verbose_name='题目数量')
    ac_submission_count = models.PositiveIntegerField(default=0, verbose_name='AC提交数')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'contest_statistics'
        verbose_name = '比赛统计信息'
        verbose_name_plural = '比赛统计信息'

    def __str__(self):
        return f'{self.contest.contest_id} - participants:{self.participant_count}'


class ContestProblem(models.Model):
    """
    比赛题目关联表
    """
    id = models.AutoField(primary_key=True, verbose_name='主键')
    contest = models.ForeignKey(
        Contest,
        on_delete=models.CASCADE,
        related_name='problems',
        verbose_name='比赛',
        db_column='contest_id'
    )
    problem = models.ForeignKey(
        'problems.Problem',
        on_delete=models.CASCADE,
        related_name='contest_problems',
        verbose_name='题目',
        db_column='problem_id'
    )
    display_order = models.CharField(max_length=10, verbose_name='题目序号(ABC)')
    display_title = models.CharField(max_length=255, verbose_name='比赛中显示的题目标题')
    score = models.PositiveIntegerField(default=None, null=True, blank=True, verbose_name='题目分数(IOI/OI赛制)')
    color = models.CharField(max_length=50, null=True, blank=True, verbose_name='气球颜色(ACM赛制)')
    accept_count = models.PositiveIntegerField(default=0, verbose_name='AC人数')
    submit_count = models.PositiveIntegerField(default=0, verbose_name='提交次数')
    first_blood_user_id = models.IntegerField(null=True, blank=True, verbose_name='一血用户ID')
    first_blood_time = models.DateTimeField(null=True, blank=True, verbose_name='一血时间')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'contest_problem'
        verbose_name = '比赛题目关联'
        verbose_name_plural = '比赛题目关联'
        unique_together = [['contest', 'display_order']]  # 同一比赛中题目序号唯一
        indexes = [
            models.Index(fields=['contest', 'display_order'], name='contest_problem_order_idx'),
            models.Index(fields=['contest', 'problem'], name='contest_problem_idx'),
            models.Index(fields=['first_blood_user_id'], name='contest_problem_fb_user_idx'),
        ]

    def __str__(self):
        return f'{self.contest.contest_id} - {self.display_order} - {self.display_title}'


class ContestRegistration(models.Model):
    """
    比赛报名表
    """
    STATUS_SUCCESS = '报名成功'
    STATUS_FAILED = '报名失败'

    STATUS_CHOICES = (
        (STATUS_SUCCESS, '报名成功'),
        (STATUS_FAILED, '报名失败'),
    )

    id = models.AutoField(primary_key=True, verbose_name='主键')
    contest = models.ForeignKey(
        Contest,
        on_delete=models.CASCADE,
        related_name='registrations',
        verbose_name='比赛',
        db_column='contest_id'
    )
    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='contest_registrations',
        verbose_name='用户',
        db_column='user_id'
    )
    register_time = models.DateTimeField(auto_now_add=True, verbose_name='报名时间')
    real_name = models.CharField(max_length=50, null=True, blank=True, verbose_name='真实姓名')
    student_id = models.CharField(max_length=50, null=True, blank=True, verbose_name='学号')
    school = models.CharField(max_length=255, null=True, blank=True, verbose_name='学校')
    phone = models.CharField(max_length=20, null=True, blank=True, verbose_name='联系电话')
    email = models.EmailField(max_length=100, null=True, blank=True, verbose_name='邮箱')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_SUCCESS,
        verbose_name='报名状态'
    )
    is_star = models.BooleanField(default=False, verbose_name='是否打星选手')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'contest_registration'
        verbose_name = '比赛报名'
        verbose_name_plural = '比赛报名'
        unique_together = [['contest', 'user']]  # 同一用户在同一比赛中只能报名一次
        indexes = [
            models.Index(fields=['contest', 'user'], name='contest_reg_contest_user_idx'),
            models.Index(fields=['contest', 'register_time'], name='contest_reg_time_idx'),
            models.Index(fields=['status'], name='contest_reg_status_idx'),
        ]

    def __str__(self):
        return f'{self.contest.contest_id} - {self.user.username} - {self.status}'


class ContestRank(models.Model):
    """
    比赛排名表(缓存排名数据,提升查询性能)
    """
    id = models.AutoField(primary_key=True, verbose_name='主键')
    contest = models.ForeignKey(
        Contest,
        on_delete=models.CASCADE,
        related_name='ranks',
        verbose_name='比赛',
        db_column='contest_id'
    )
    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='contest_ranks',
        verbose_name='用户',
        db_column='user_id'
    )
    rank = models.PositiveIntegerField(default=0, verbose_name='排名')
    total_score = models.FloatField(default=0.0, verbose_name='总分(IOI/OI赛制)')
    total_time = models.PositiveIntegerField(default=0, verbose_name='总罚时(分钟,ACM赛制)')
    ac_count = models.PositiveIntegerField(default=0, verbose_name='AC题目数')
    submit_count = models.PositiveIntegerField(default=0, verbose_name='提交次数')
    problem_status = models.JSONField(
        default=dict,
        verbose_name='每题状态(JSON: {A: {status, time, score, tries}})'
    )
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'contest_rank'
        verbose_name = '比赛排名'
        verbose_name_plural = '比赛排名'
        unique_together = [['contest', 'user']]  # 同一用户在同一比赛中只有一条排名记录
        indexes = [
            models.Index(fields=['contest', 'rank'], name='contest_rank_contest_rank_idx'),
            models.Index(fields=['contest', 'user'], name='contest_rank_contest_user_idx'),
            models.Index(fields=['update_time'], name='contest_rank_update_time_idx'),
        ]

    def __str__(self):
        return f'{self.contest.contest_id} - {self.user.username} - Rank:{self.rank}'


class ContestAnnouncement(models.Model):
    """
    比赛公告表
    """
    id = models.AutoField(primary_key=True, verbose_name='主键')
    contest = models.ForeignKey(
        Contest,
        on_delete=models.CASCADE,
        related_name='announcements',
        verbose_name='比赛',
        db_column='contest_id'
    )
    title = models.CharField(max_length=255, verbose_name='公告标题')
    content = models.TextField(verbose_name='公告内容')
    is_important = models.BooleanField(default=False, verbose_name='是否重要(置顶)')
    publisher_id = models.IntegerField(verbose_name='发布人ID')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='发布时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'contest_announcement'
        verbose_name = '比赛公告'
        verbose_name_plural = '比赛公告'
        ordering = ['-is_important', '-create_time']  # 重要公告在前，然后按时间倒序
        indexes = [
            models.Index(fields=['contest', 'is_important', 'create_time'], name='contest_ann_important_idx'),
            models.Index(fields=['contest', 'create_time'], name='contest_ann_time_idx'),
            models.Index(fields=['publisher_id'], name='contest_ann_publisher_idx'),
        ]

    def __str__(self):
        return f'{self.contest.contest_id} - {self.title}'