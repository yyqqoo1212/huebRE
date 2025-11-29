# -*- coding: utf-8 -*-


from django.contrib import admin

from .models import Problem, ProblemData


@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = ('problem_id', 'title', 'author', 'auth', 'create_time')
    search_fields = ('problem_id', 'title', 'author')
    list_filter = ('auth', 'create_time')


@admin.register(ProblemData)
class ProblemDataAdmin(admin.ModelAdmin):
    list_display = ('problem_id', 'title', 'level', 'submission', 'ac', 'score')
    search_fields = ('problem__problem_id', 'title')
    list_filter = ('level', 'auth')

