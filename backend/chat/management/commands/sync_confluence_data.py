from django.core.management.base import BaseCommand
from chat.models import ConfluenceSync
from chat.utils.confluence import fetch_confluence_pages

class Command(BaseCommand):
    help = 'Sync Confluence pages for all configured syncs'

    def handle(self, *args, **options):
        for sync in ConfluenceSync.objects.all():
            try:
                self.stdout.write(f"Syncing Confluence pages for {sync.space_url}")
                fetch_confluence_pages(sync)
                self.stdout.write(self.style.SUCCESS(f"Successfully synced Confluence pages for {sync.space_url}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error syncing Confluence pages for {sync.space_url}: {e}"))