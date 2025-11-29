# -*- coding: utf-8 -*-


from django.test import TestCase

from .models import Problem, ProblemData


class ProblemModelTests(TestCase):
    def test_create_problem_and_stats(self):
        problem = Problem.objects.create(
            author='system',
            title='示例题目',
            content='描述',
        )
        stats = ProblemData.objects.create(problem=problem, title=problem.title)

        self.assertEqual(stats.problem_id, problem.problem_id)
        self.assertEqual(stats.title, '示例题目')

