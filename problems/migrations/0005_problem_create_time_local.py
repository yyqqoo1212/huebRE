# Generated manually: store create_time in Asia/Shanghai local time

from django.db import migrations, models
import problems.models


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0004_alter_problemdata_ac_alter_problemdata_ce_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='problem',
            name='create_time',
            field=models.DateTimeField(
                default=problems.models._problem_create_time_default,
                verbose_name='创建时间',
            ),
        ),
    ]
