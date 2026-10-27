from django.core.management.base import BaseCommand

from core import services


class Command(BaseCommand):
    help = "Bill all in-progress sessions (run from cron every ~10-30s). Idempotent."

    def handle(self, *args, **options):
        for pk, charged, status in services.bill_all_active_sessions():
            self.stdout.write(f"session {pk}: charged {charged} min, status={status}")
