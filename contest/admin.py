# -*- coding: utf-8 -*-

from django.contrib import admin

from .models import (
    Contest,
    ContestTimeConfig,
    ContestRuleConfig,
    ContestPermissionConfig,
    ContestStatistics
)


@admin.register(Contest)
class ContestAdmin(admin.ModelAdmin):
    list_display = ('contest_id', 'contest_name', 'creator_id', 'create_time')
    search_fields = ('contest_id', 'contest_name', 'creator_id')
    list_filter = ('create_time',)
    readonly_fields = ('contest_id', 'create_time', 'update_time')


@admin.register(ContestTimeConfig)
class ContestTimeConfigAdmin(admin.ModelAdmin):
    list_display = ('id', 'contest', 'start_time', 'end_time', 'status')
    search_fields = ('contest__contest_id', 'contest__contest_name')
    list_filter = ('status', 'start_time')
    readonly_fields = ('id', 'create_time', 'update_time')


@admin.register(ContestRuleConfig)
class ContestRuleConfigAdmin(admin.ModelAdmin):
    list_display = ('id', 'contest', 'contest_type', 'contest_mode', 'penalty_time')
    search_fields = ('contest__contest_id', 'contest__contest_name')
    list_filter = ('contest_type', 'contest_mode')
    readonly_fields = ('id', 'create_time', 'update_time')


@admin.register(ContestPermissionConfig)
class ContestPermissionConfigAdmin(admin.ModelAdmin):
    list_display = ('id', 'contest', 'visibility', 'show_rank', 'show_others_code', 'show_testcase')
    search_fields = ('contest__contest_id', 'contest__contest_name')
    list_filter = ('visibility', 'show_rank', 'show_others_code', 'show_testcase')
    readonly_fields = ('id', 'create_time', 'update_time')


@admin.register(ContestStatistics)
class ContestStatisticsAdmin(admin.ModelAdmin):
    list_display = ('id', 'contest', 'participant_count', 'registration_count', 'submission_count', 'problem_count', 'ac_submission_count')
    search_fields = ('contest__contest_id', 'contest__contest_name')
    readonly_fields = ('id', 'update_time')

