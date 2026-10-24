from unittest import mock

import requests
from django.test import SimpleTestCase

from clashroyale.api import ApiError, ClashRoyaleClient, NotFound


def _resp(status, body=None):
    r = mock.Mock(status_code=status, reason='reason')
    r.json.return_value = body if body is not None else {}
    return r


class ClientTests(SimpleTestCase):
    def setUp(self):
        self.sleeps = []
        self.client = ClashRoyaleClient(api_key='k', base_url='https://x', sleep=self.sleeps.append)
        self.session = mock.Mock()
        self.client._local.session = self.session

    def test_retries_429_then_succeeds(self):
        self.session.get.side_effect = [_resp(429), _resp(503), _resp(200, {'ok': 1})]
        self.assertEqual(self.client.get('/p'), {'ok': 1})
        self.assertEqual(len(self.sleeps), 2)
        self.assertLess(self.sleeps[0], self.sleeps[1])

    def test_gives_up_after_max_attempts(self):
        self.session.get.return_value = _resp(429, {'reason': 'throttled'})
        with self.assertRaises(ApiError) as ctx:
            self.client.get('/p')
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(self.session.get.call_count, 5)

    def test_retries_network_errors(self):
        self.session.get.side_effect = [requests.ConnectionError('boom'), _resp(200, [])]
        self.assertEqual(self.client.get('/p'), [])

    def test_404_raises_not_found_without_retry(self):
        self.session.get.return_value = _resp(404, {'reason': 'notFound'})
        with self.assertRaises(NotFound):
            self.client.get('/p')
        self.assertEqual(self.session.get.call_count, 1)

    def test_403_not_retried(self):
        self.session.get.return_value = _resp(403, {'reason': 'accessDenied.invalidIp'})
        with self.assertRaises(ApiError) as ctx:
            self.client.get('/p')
        self.assertEqual(ctx.exception.reason, 'accessDenied.invalidIp')
        self.assertEqual(self.session.get.call_count, 1)

    def test_battlelog_encodes_tag(self):
        self.session.get.return_value = _resp(200, [])
        self.client.battlelog('#ABC')
        self.assertEqual(self.session.get.call_args.args[0], 'https://x/players/%23ABC/battlelog')

    def test_top_players_follows_cursor(self):
        self.session.get.side_effect = [
            _resp(200, {'items': [{'tag': '#1'}, {'tag': '#2'}], 'paging': {'cursors': {'after': 'c'}}}),
            _resp(200, {'items': [{'tag': '#3'}], 'paging': {'cursors': {}}}),
        ]
        players = self.client.top_players(limit=3)
        self.assertEqual([p['tag'] for p in players], ['#1', '#2', '#3'])
        self.assertEqual(self.session.get.call_args.kwargs['params'], {'limit': 1, 'after': 'c'})
