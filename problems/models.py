from django.db import models


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
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
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
    ac = models.IntegerField(default=0, verbose_name='通过数')
    tle = models.IntegerField(default=0, verbose_name='超时数')
    mle = models.IntegerField(default=0, verbose_name='内存超限数')
    ce = models.IntegerField(default=0, verbose_name='编译错误数')
    pe = models.IntegerField(default=0, verbose_name='答案错误数')
    tag = models.TextField(blank=True, verbose_name='题目标签')
    auth = models.IntegerField(choices=Problem.AUTH_CHOICES, default=Problem.PUBLIC, verbose_name='题目权限')
    score = models.IntegerField(default=100, verbose_name='题目分数')

    class Meta:
        db_table = 'problem_data'
        verbose_name = '题目统计'
        verbose_name_plural = '题目统计'

    def __str__(self) -> str:
        return f'{self.problem_id} - {self.title}'

    @property
    def problem_id(self) -> str:
        return self.problem.problem_id

