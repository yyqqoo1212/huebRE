# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0002_submission_problem_problem_auth_idx_and_more'),
    ]

    operations = [
        # 重命名字段：pe -> wr
        migrations.RenameField(
            model_name='problemdata',
            old_name='pe',
            new_name='wr',
        ),
        # 添加新字段：re (Runtime Error)
        migrations.AddField(
            model_name='problemdata',
            name='re',
            field=models.IntegerField(default=0, verbose_name='运行时错误数(Runtime Error)'),
        ),
        # 迁移数据：将pe的数据迁移到wr
        # 注意：由于RenameField会自动处理数据迁移，所以不需要额外的数据迁移操作
        # 但是需要确保新字段re有默认值0，这在AddField中已经设置了
    ]

