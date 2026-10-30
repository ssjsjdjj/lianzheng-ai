"""Catch source packages that omit a script referenced by the application."""
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from lianzheng.app import create_app


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        url = values.get('src') if tag == 'script' else values.get('href') if tag == 'link' else None
        if url and url.startswith('/static/'):
            self.urls.append(url)


def test_every_application_script_and_stylesheet_is_served(tmp_path):
    with TestClient(create_app(tmp_path / 'assets.sqlite3', seed=False)) as client:
        parser = Assets()
        parser.feed(client.get('/').text)
        assert '/static/model-settings.js' in parser.urls
        for url in parser.urls:
            response = client.get(url)
            assert response.status_code == 200, f'Missing packaged UI asset: {url}'
            assert response.content, f'Empty UI asset: {url}'
            if url.endswith('.js'):
                assert 'javascript' in response.headers['content-type']
