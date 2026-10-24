"""Clash Royale API client. See specs/clash-royale/01-data-sources.md."""

import random
import threading
import time
from urllib.parse import quote

import requests
from django.conf import settings

RETRY_STATUSES = {429, 503}
MAX_ATTEMPTS = 5
TIMEOUT = 20


class ApiError(Exception):
    def __init__(self, status, reason, path):
        self.status = status
        self.reason = reason
        super().__init__(f'{status} {reason} for {path}')


class NotFound(ApiError):
    pass


class ClashRoyaleClient:
    def __init__(self, api_key=None, base_url=None, sleep=time.sleep):
        self.api_key = api_key if api_key is not None else settings.CLASHROYALE_API_KEY
        if not self.api_key:
            raise ApiError(0, 'CLASHROYALE_API_KEY is not set', '-')
        self.base_url = base_url or settings.CLASHROYALE_API_BASE
        self._sleep = sleep
        # requests.Session is not guaranteed thread-safe; use one per thread.
        self._local = threading.local()

    def _session(self):
        if not hasattr(self._local, 'session'):
            s = requests.Session()
            s.headers['Authorization'] = f'Bearer {self.api_key}'
            self._local.session = s
        return self._local.session

    def get(self, path, params=None):
        url = self.base_url + path
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = self._session().get(url, params=params, timeout=TIMEOUT)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == MAX_ATTEMPTS:
                    raise ApiError(0, f'network error: {exc}', path) from exc
            else:
                if resp.status_code == 200:
                    return resp.json()
                reason = _reason(resp)
                if resp.status_code == 404:
                    raise NotFound(404, reason, path)
                if resp.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                    raise ApiError(resp.status_code, reason, path)
            # Exponential backoff with jitter: ~1s, 2s, 4s, 8s.
            self._sleep(2 ** (attempt - 1) + random.uniform(0, 1))
        raise AssertionError('unreachable')

    def cards(self):
        return self.get('/cards')

    def top_players(self, limit=1000):
        players, after = [], None
        while len(players) < limit:
            params = {'limit': limit - len(players)}
            if after:
                params['after'] = after
            page = self.get('/locations/global/pathoflegend/players', params)
            players.extend(page.get('items', []))
            after = page.get('paging', {}).get('cursors', {}).get('after')
            if not after or not page.get('items'):
                break
        return players[:limit]

    def battlelog(self, tag):
        return self.get(f'/players/{quote(tag, safe="")}/battlelog')


def _reason(resp):
    try:
        return resp.json().get('reason', resp.reason)
    except ValueError:
        return resp.reason
