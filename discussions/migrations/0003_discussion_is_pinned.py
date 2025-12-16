# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('discussions', '0002_discussion_views_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='discussion',
            name='is_pinned',
            field=models.BooleanField(default=False, verbose_name='是否置顶'),
        ),
    ]

