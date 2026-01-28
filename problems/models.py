from django.db import models
from django.utils import timezone


def _problem_create_time_default():
    """写入数据库时使用东八区（Asia/Shanghai）本地时间，便于直接查库看到正确时间。"""
    return timezone.make_naive(
        timezone.localtime(timezone.now()),
        timezone.get_current_timezone()
    )


class Problem(models.Model):
    """
    Problem 题目详细信息
    """

    PUBLIC = 1
    PRIVATE = 2
    CONTEST = 3

    AUTH_CHOICES = (
        (PUBLIC, '公开题目'),
        (PRIVATE, '私密题目'),
        (CONTEST, '比赛题目'),
    )

    problem_id = models.AutoField(primary_key=True, verbose_name='题目ID')
    author = models.CharField(max_length=100, verbose_name='题目作者')
    create_time = models.DateTimeField(default=_problem_create_time_default, verbose_name='创建时间')
    title = models.CharField(max_length=255, verbose_name='题目标题')
    content = models.TextField(blank=True, verbose_name='题目描述')
    input_description = models.TextField(blank=True, verbose_name='输入描述')
    output_description = models.TextField(blank=True, verbose_name='输出描述')
    input_demo = models.TextField(blank=True, verbose_name='输入样例')
    output_demo = models.TextField(blank=True, verbose_name='输出样例')
    time_limit = models.IntegerField(default=1000, verbose_name='时间限制(ms)')
    memory_limit = models.IntegerField(default=256, verbose_name='内存限制(MB)')
    hint = models.TextField(blank=True, verbose_name='提示信息')
    auth = models.IntegerField(choices=AUTH_CHOICES, default=PUBLIC, verbose_name='题目权限')

    class Meta:
        db_table = 'problem'
        ordering = ['-create_time']
        verbose_name = '题目'
        verbose_name_plural = '题目'
        indexes = [
            models.Index(fields=['auth'], name='problem_auth_idx'),
            models.Index(fields=['problem_id'], name='problem_id_idx'),
        ]

    def __str__(self) -> str:
        return f'{self.problem_id} - {self.title}'


class ProblemData(models.Model):
    """
    ProblemData 题目简要信息
    """

    LEVEL_EASY = 1
    LEVEL_MEDIUM = 2
    LEVEL_HARD = 3

    LEVEL_CHOICES = (
        (LEVEL_EASY, '简单'),
        (LEVEL_MEDIUM, '中等'),
        (LEVEL_HARD, '困难'),
    )

    problem = models.OneToOneField(
        Problem,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='stat',
        verbose_name='题目',
    )
    title = models.CharField(max_length=255, verbose_name='题目标题')
    level = models.IntegerField(choices=LEVEL_CHOICES, default=LEVEL_EASY, verbose_name='题目难度')
    submission = models.IntegerField(default=0, verbose_name='提交总数')
    ac = models.IntegerField(default=0, verbose_name='通过数(Accepted)')
    wr = models.IntegerField(default=0, verbose_name='答案错误数(Wrong Answer)')
    tle = models.IntegerField(default=0, verbose_name='超时数(Time Limit Exceeded)')
    mle = models.IntegerField(default=0, verbose_name='内存超限数(Memory Limit Exceeded)')
    re = models.IntegerField(default=0, verbose_name='运行时错误数(Runtime Error)')
    ce = models.IntegerField(default=0, verbose_name='编译错误数(Compile Error)')
    tag = models.TextField(blank=True, verbose_name='题目标签')
    auth = models.IntegerField(choices=Problem.AUTH_CHOICES, default=Problem.PUBLIC, verbose_name='题目权限')
    score = models.IntegerField(default=100, verbose_name='题目分数')

    class Meta:
        db_table = 'problem_data'
        verbose_name = '题目统计'
        verbose_name_plural = '题目统计'
        indexes = [
            models.Index(fields=['auth', 'level'], name='problem_data_auth_level_idx'),
            models.Index(fields=['title'], name='problem_data_title_idx'),
        ]

    def __str__(self) -> str:
        return f'{self.problem_id} - {self.title}'

    @property
    def problem_id(self) -> str:
        return self.problem.problem_id


class Submission(models.Model):
    """
    Submission 提交记录
    """
    
    STATUS_ACCEPTED = 0
    STATUS_WRONG_ANSWER = -1
    STATUS_TIME_LIMIT_EXCEEDED = 1
    STATUS_MEMORY_LIMIT_EXCEEDED = 3
    STATUS_RUNTIME_ERROR = 4
    STATUS_COMPILE_ERROR = 5
    STATUS_SYSTEM_ERROR = 6
    STATUS_JUDGING = 7
    
    STATUS_CHOICES = (
        (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_WRONG_ANSWER, 'Wrong Answer'),
        (STATUS_TIME_LIMIT_EXCEEDED, 'Time Limit Exceeded'),
        (STATUS_MEMORY_LIMIT_EXCEEDED, 'Memory Limit Exceeded'),
        (STATUS_RUNTIME_ERROR, 'Runtime Error'),
        (STATUS_COMPILE_ERROR, 'Compile Error'),
        (STATUS_SYSTEM_ERROR, 'System Error'),
        (STATUS_JUDGING, 'Judging'),
    )
    
    submission_id = models.AutoField(primary_key=True, verbose_name='提交ID')
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='submissions', verbose_name='题目')
    user = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='submissions', verbose_name='用户')
    code = models.TextField(verbose_name='提交代码')
    language = models.CharField(max_length=20, verbose_name='编程语言')
    status = models.IntegerField(choices=STATUS_CHOICES, default=STATUS_JUDGING, verbose_name='判题状态')
    result = models.JSONField(default=dict, verbose_name='判题结果详情')
    cpu_time = models.IntegerField(default=0, verbose_name='CPU时间(ms)')
    memory = models.BigIntegerField(default=0, verbose_name='内存使用(字节)')
    code_length = models.IntegerField(default=0, verbose_name='代码长度(字节)')
    submit_time = models.DateTimeField(auto_now_add=True, verbose_name='提交时间')
    
    class Meta:
        db_table = 'submission'
        ordering = ['-submit_time']
        verbose_name = '提交记录'
        verbose_name_plural = '提交记录'
        indexes = [
            models.Index(fields=['problem', 'user'], name='submission_problem_user_idx'),
            models.Index(fields=['status'], name='submission_status_idx'),
            models.Index(fields=['submit_time'], name='submission_time_idx'),
        ]
    
    def __str__(self) -> str:
        return f'{self.submission_id} - {self.problem.title} - {self.user.username}'
