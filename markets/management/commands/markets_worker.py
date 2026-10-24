import time

from django.core.management.base import BaseCommand

from markets import clock, scheduler


class Command(BaseCommand):
    help = "Open, close and settle windowed UP/DOWN markets in a loop (each game on its own clock)."

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=float, default=2.0, help='real seconds between ticks')
        parser.add_argument('--once', action='store_true', help='run a single tick and exit')

    def handle(self, *args, interval, once, **options):
        while True:
            for game, result in scheduler.tick_all().items():
                if once or any(result.values()):
                    now = clock.now(game)
                    self.stdout.write(f'{game:<12} {now:%Y-%m-%d %H:%M:%S} UTC  {clock.mode(game)["label"]}  {result}')
            if once:
                return
            time.sleep(interval)
