from django.db import models


class User(models.Model):
    GENDER_CHOICES = [
        ('M', '男'),
        ('F', '女'),
    ]
    
    username = models.CharField(max_length=50, unique=True)
    password_hash = models.CharField(max_length=255)
    email = models.EmailField(max_length=100, unique=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True, default='')
    motto = models.CharField(max_length=255, blank=True, default='')
    avatar_url = models.CharField(max_length=255, blank=True, default='')
    total_submissions = models.IntegerField(default=0)
    accepted_submissions = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    permission = models.IntegerField(default=0)

    class Meta:
        db_table = 'user'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.username
