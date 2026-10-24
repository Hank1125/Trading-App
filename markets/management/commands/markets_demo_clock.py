from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from markets import clock
from markets.models import ClockState


class Command(BaseCommand):
    help = 'Start (or stop) the accelerated replay clock shared by the web app and the worker.'

    def add_arguments(self, parser):
        parser.add_argument('--start', default='2026-05-10T15:00:00+00:00', help='demo time to start at (ISO)')
        parser.add_argument('--speed', default='60', help='demo seconds per real second (60 = 1 demo hour/min)')
        parser.add_argument('--label', default='BLAST Major Salt Lake City 2026, real results')
        parser.add_argument('--stop', action='store_true', help='remove the demo clock (back to live time)')

    def handle(self, *args, start, speed, label, stop, **options):
        if stop:
            ClockState.objects.filter(pk=1).delete()
            self.stdout.write('demo clock removed; markets use live UTC time')
            return
        try:
            demo_start = datetime.fromisoformat(start)
            speed_value = Decimal(speed)
        except ValueError as e:
            raise CommandError(str(e)) from None
        if demo_start.tzinfo is None or not (Decimal(1) <= speed_value <= Decimal(3600)):
            raise CommandError('start needs a timezone and speed must be between 1 and 3600')
        ClockState.objects.update_or_create(
            pk=1,
            defaults={'demo_start': demo_start, 'real_start': clock.real_now(), 'speed': speed_value, 'label': label},
        )
        self.stdout.write(f'demo clock started at {demo_start.isoformat()} x{speed_value}')
