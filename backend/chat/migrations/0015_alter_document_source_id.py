from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0014_jiraissue_assignee_jiraissue_resolution_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="source_id",
            field=models.CharField(max_length=500),
        ),
    ]
