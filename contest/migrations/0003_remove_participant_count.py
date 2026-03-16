from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('contest', '0002_contestannouncement_contestproblem_contestrank_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='conteststatistics',
            name='participant_count',
        ),
    ]

