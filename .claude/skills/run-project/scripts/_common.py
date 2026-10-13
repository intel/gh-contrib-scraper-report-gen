# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for the run-project skill scripts (stdlib only).

Tokens are read from the environment or the project's .env and are never printed.
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API_URL = 'https://api.github.com'
# Keys from .env that affect networking; loaded into this process only
NETWORK_KEYS = ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'no_proxy',
                'REQUESTS_CA_BUNDLE', 'SSL_CERT_FILE')
ENV_LINE = re.compile(r'^\s*([^#][^=]+)=(.*)$')  # same pattern as run.ps1
SECRET_KEY = re.compile(r'TOKEN|SECRET|PASSWORD|PASSWD|KEY', re.IGNORECASE)
# Process environment as it was before load_settings() added .env values
ORIGINAL_ENVIRON = dict(os.environ)


def configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


def fail(message: str, code: int = 1) -> None:
    print(f'ERROR: {message}', file=sys.stderr)
    sys.exit(code)


def find_project_root(start: str | None = None) -> str | None:
    """Walk up from start (default: cwd) to the folder containing src/main.py and run.sh."""
    path = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(path, 'src', 'main.py')) and os.path.isfile(os.path.join(path, 'run.sh')):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def read_env_file(path: str) -> dict[str, str]:
    """Parse a .env file the way run.ps1 does (KEY=value, # comments; values kept verbatim, quotes included)."""
    values: dict[str, str] = {}
    if not os.path.isfile(path):
        return values
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            match = ENV_LINE.match(line.rstrip('\r\n'))
            if match:
                values[match.group(1).strip()] = match.group(2).strip()
    return values


def load_settings(root: str) -> dict[str, str]:
    """Return effective settings as the run scripts see them: .env is loaded after, and so overrides, the environment."""
    env_file = read_env_file(os.path.join(root, '.env'))
    settings = {k: v for k, v in ORIGINAL_ENVIRON.items() if k.startswith('GITHUB_') or k in NETWORK_KEYS}
    settings.update(env_file)
    # Make proxy/CA settings visible to urllib in this process
    for key in NETWORK_KEYS:
        if key in env_file:
            os.environ[key] = env_file[key]
    return settings


def parse_tokens(token_str: str) -> dict[str, str]:
    """Parse GITHUB_TOKEN: a single token (key '*') or an owner:token,owner2:token2 map (keys lowercased)."""
    token_str = (token_str or '').strip()
    if not token_str:
        return {}
    if ':' not in token_str:
        return {'*': token_str}
    tokens = {}
    for pair in token_str.split(','):
        owner, _, token = pair.strip().partition(':')
        if owner and token:
            tokens[owner.strip().lower()] = token.strip()
    return tokens


def fingerprint(token: str) -> str:
    return f'...{token[-4:]}' if token and len(token) > 8 else '(short)'


def redact_url(url: str) -> str:
    """Hide credentials embedded in a proxy URL."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return '(unparseable)'
    if parts.username or parts.password:
        netloc = '***@' + (parts.hostname or '') + (f':{parts.port}' if parts.port else '')
        return urllib.parse.urlunsplit(parts._replace(netloc=netloc))
    return url


def ssl_context(settings: dict[str, str], insecure: bool = False, ca_bundle: str | None = None) -> ssl.SSLContext:
    if insecure:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    cafile = ca_bundle or settings.get('REQUESTS_CA_BUNDLE') or settings.get('SSL_CERT_FILE')
    return ssl.create_default_context(cafile=cafile if cafile and os.path.isfile(cafile) else None)


def graphql_url(api_url: str) -> str:
    api_url = api_url.rstrip('/')
    if api_url.endswith('/api/v3'):  # GitHub Enterprise Server
        return api_url[:-len('/v3')] + '/graphql'
    return api_url + '/graphql'


class GitHubClient:
    """Minimal read-only GitHub REST/GraphQL client with pagination and rate-limit handling."""

    def __init__(self, token: str | None, api_url: str, context: ssl.SSLContext, timeout: int = 30) -> None:
        self.token = token
        self.api_url = api_url.rstrip('/')
        self.context = context
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))

    def _request(self, method: str, url: str, body: dict | None = None) -> tuple[int, dict, object]:
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'gh-contrib-scraper-setup',
                   'X-GitHub-Api-Version': '2022-11-28'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        data = json.dumps(body).encode('utf-8') if body is not None else None
        if data is not None:
            headers['Content-Type'] = 'application/json'
        for attempt in range(3):
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    payload = response.read().decode('utf-8')
                    return response.status, dict(response.headers), json.loads(payload) if payload else None
            except urllib.error.HTTPError as e:
                response_headers = dict(e.headers or {})
                try:
                    payload = json.loads(e.read().decode('utf-8') or 'null')
                except ValueError:
                    payload = None
                limited = e.code in (403, 429) and (response_headers.get('Retry-After')
                                                     or response_headers.get('X-RateLimit-Remaining') == '0')
                if limited and attempt < 2:
                    wait = int(response_headers.get('Retry-After') or 0)
                    if not wait and response_headers.get('X-RateLimit-Reset'):
                        wait = max(0, int(response_headers['X-RateLimit-Reset']) - int(time.time())) + 1
                    if wait <= 90:
                        time.sleep(wait or 5)
                        continue
                return e.code, response_headers, payload
            except (urllib.error.URLError, OSError) as e:
                # Connection-level failure: DNS, proxy, TLS, timeout
                return 0, {}, {'message': str(getattr(e, 'reason', e))}
        return 0, {}, None

    def get(self, path: str, params: dict | None = None) -> tuple[int, dict, object]:
        url = path if path.startswith('http') else f'{self.api_url}{path}'
        if params:
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
        return self._request('GET', url)

    def paginate(self, path: str, params: dict | None = None, key: str | None = None, limit: int = 1000) -> list:
        """Follow Link rel="next" headers; key selects the list inside an object response (e.g. search 'items')."""
        items: list = []
        status, headers, payload = self.get(path, dict(params or {}, per_page=100))
        while status == 200 and payload is not None:
            page = payload.get(key, []) if key and isinstance(payload, dict) else payload
            items.extend(page if isinstance(page, list) else [])
            match = re.search(r'<([^>]+)>;\s*rel="next"', headers.get('Link', ''))
            if len(items) >= limit or not match:
                break
            status, headers, payload = self._request('GET', match.group(1))
        return items[:limit]

    def graphql(self, query: str, variables: dict) -> tuple[int, object]:
        status, _, payload = self._request('POST', graphql_url(self.api_url), {'query': query, 'variables': variables})
        return status, payload


def describe_error(status: int, payload) -> str:
    message = payload.get('message') if isinstance(payload, dict) else None
    return f'HTTP {status}' + (f': {message}' if message else '')
