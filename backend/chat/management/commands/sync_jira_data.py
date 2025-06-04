from django.core.management.base import BaseCommand
from chat.models import JiraSync
from chat.utils.jira import fetch_jira_issues

class Command(BaseCommand):
    help = 'Sync Jira issues and comments for all JiraSync entries'

    def handle(self, *args, **options):
        syncs = JiraSync.objects.all()

        if not syncs.exists():
            self.stdout.write(self.style.WARNING('No Jira Syncs found.'))
            return

        for sync in syncs:
            try:
                fetch_jira_issues(sync)
                self.stdout.write(self.style.SUCCESS(f'Successfully synced issues for {sync.board_url}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error syncing issues for {sync.board_url}: {str(e)}'))