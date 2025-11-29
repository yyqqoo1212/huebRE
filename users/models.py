# -*- coding: utf-8 -*-


from django.db import models


class User(models.Model):
    GENDER_CHOICES = [
        ('M', '男'),
        ('F', '女'),
    ]
    
    STATUS_CHOICES = [
        ('normal', '正常'),
        ('banned', '封禁'),
    ]
    
    username = models.CharField(max_length=50, unique=True, verbose_name='用户名')
    password_hash = models.CharField(max_length=255)
    email = models.EmailField(max_length=100, unique=True, verbose_name='邮箱')
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True, default='M', verbose_name='性别')
    motto = models.CharField(max_length=80, blank=True, default='', verbose_name='个性签名')
    avatar_url = models.CharField(max_length=500, blank=True, default='', verbose_name='头像URL')
    # 新增字段
    student_id = models.CharField(max_length=50, blank=True, default='', verbose_name='学号')
    class_name = models.CharField(max_length=100, blank=True, default='', verbose_name='班级')
    real_name = models.CharField(max_length=50, blank=True, default='', verbose_name='真实姓名')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='normal', verbose_name='用户状态')
    last_login_time = models.DateTimeField(null=True, blank=True, verbose_name='最后登录时间')
    
    total_submissions = models.IntegerField(default=0)
    accepted_submissions = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    permission = models.IntegerField(default=0)

    class Meta:
        db_table = 'user'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.username
