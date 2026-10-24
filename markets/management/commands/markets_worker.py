import time

from django.core.management.base import BaseCommand

from markets import clock, scheduler


class Command(BaseCommand):
    help = 'Open, close and settle windowed UP/DOWN markets in a loop (uses the shared market clock).'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=float, default=2.0, help='real seconds between ticks')
        parser.add_argument('--once', action='store_true', help='run a single tick and exit')

    def handle(self, *args, interval, once, **options):
        while True:
            now = clock.now()
            result = scheduler.tick(now)
            if once or any(result.values()):
                self.stdout.write(f'{now:%Y-%m-%d %H:%M:%S} UTC  {clock.mode()["label"]}  {result}')
            if once:
                return
            time.sleep(interval)
