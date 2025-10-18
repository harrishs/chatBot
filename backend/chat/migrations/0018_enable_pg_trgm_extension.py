from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0017_document_rerank_cache"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm",
            reverse_sql="DROP EXTENSION IF EXISTS pg_trgm",
        ),
    ]
