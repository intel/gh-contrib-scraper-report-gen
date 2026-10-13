# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Discover repositories (and PR target branches) a user committed to since a date. Read-only.

Usage: python discover.py USERNAME --since YYYY-MM-DD [--until YYYY-MM-DD] [--root DIR] [--api-url URL]
                          [--max-repos N] [--max-prs N] [--ca-bundle PATH] [--no-verify-ssl]

Uses every token in GITHUB_TOKEN (environment or the project's .env), then merges:
  1. GraphQL contributionsCollection (commits/PRs per repository; default branches only)
  2. PR search (repositories where the user opened PRs; finds work outside default branches)
  3. Commit search (fallback when GraphQL is unavailable to a token)
  4. Repositories the token can access, pushed to since the date (fits fine-grained tokens, which
     often can't search or see contributions in their organisation)
Every candidate is verified with the same per-repository author query the scraper uses.
Prints JSON; tokens are never printed.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import re
import sys

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__

from _common import (DEFAULT_API_URL, GitHubClient, configure_stdout, describe_error, fail,  # noqa: E402
                     find_project_root, load_settings, parse_tokens, ssl_context)

CONTRIBUTIONS_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      restrictedContributionsCount
      commitContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner isFork isArchived defaultBranchRef { name } }
        contributions { totalCount }
      }
      pullRequestContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner isFork isArchived defaultBranchRef { name } }
        contributions { totalCount }
      }
    }
  }
}"""


def parse_day(value: str) -> datetime:
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    fail(f'Unsupported date: {value} (use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)')
    raise AssertionError


def iso(moment: datetime) -> str:
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


class Discovery:

    def __init__(self, username: str, since: datetime, until: datetime) -> None:
        self.username = username
        self.since, self.until = since, until
        self.repos: dict[str, dict] = {}
        self.warnings: list[str] = []
        self.restricted = 0

    def candidate(self, full_name: str, source: str, token_key: str, **extra) -> dict:
        key = full_name.lower()
        repo = self.repos.setdefault(key, {'name': full_name, 'sources': {}, 'token_keys': set(),
                                           'pr_base_branches': set()})
        repo['sources'][source] = repo['sources'].get(source, 0) + extra.pop('count', 1)
        repo['token_keys'].add(token_key)
        for k, v in extra.items():
            if v is not None:
                repo[k] = v
        return repo

    def from_graphql(self, client: GitHubClient, token_key: str) -> bool:
        start = self.since
        while start < self.until:
            end = min(start + timedelta(days=365) - timedelta(seconds=1), self.until)
            status, payload = client.graphql(CONTRIBUTIONS_QUERY, {'login': self.username, 'from': iso(start), 'to': iso(end)})
            data = (payload or {}).get('data') if isinstance(payload, dict) else None
            collection = ((data or {}).get('user') or {}).get('contributionsCollection')
            if status != 200 or not collection:
                errors = payload.get('errors') if isinstance(payload, dict) else None
                detail = errors[0].get('message') if errors else describe_error(status, payload)
                self.warnings.append(f'[{token_key}] GraphQL contributions unavailable ({detail}); using search instead')
                return False
            self.restricted += collection.get('restrictedContributionsCount') or 0
            for field, source in (('commitContributionsByRepository', 'graphql_commits'),
                                  ('pullRequestContributionsByRepository', 'graphql_prs')):
                entries = collection.get(field) or []
                if len(entries) == 100:
                    self.warnings.append(f'[{token_key}] {field} hit the 100-repository cap; some may be missing')
                for entry in entries:
                    repo = entry['repository']
                    self.candidate(repo['nameWithOwner'], source, token_key, count=entry['contributions']['totalCount'],
                                   fork=repo.get('isFork'), archived=repo.get('isArchived'),
                                   default_branch=(repo.get('defaultBranchRef') or {}).get('name'))
            start = end + timedelta(seconds=1)
        return True

    def from_pr_search(self, client: GitHubClient, token_key: str, max_prs: int) -> list[dict]:
        query = f'is:pr author:{self.username} updated:>={self.since.strftime("%Y-%m-%d")}'
        status, _, payload = client.get('/search/issues', {'q': query, 'per_page': 1})
        if status != 200:
            self.warnings.append(f'[{token_key}] PR search failed: {describe_error(status, payload)}')
            return []
        items = client.paginate('/search/issues', {'q': query}, key='items', limit=1000)
        if payload.get('total_count', 0) > 1000:
            self.warnings.append(f'[{token_key}] PR search capped at 1000 of {payload["total_count"]} results')
        prs = []
        for item in items:
            full_name = item.get('repository_url', '').split('/repos/')[-1]
            if full_name:
                self.candidate(full_name, 'pr_search', token_key)
                prs.append({'repo': full_name, 'number': item.get('number')})
        return prs[:max_prs]

    def from_commit_search(self, client: GitHubClient, token_key: str) -> None:
        query = f'author:{self.username} author-date:{self.since.strftime("%Y-%m-%d")}..{self.until.strftime("%Y-%m-%d")}'
        items = client.paginate('/search/commits', {'q': query}, key='items', limit=1000)
        for item in items:
            full_name = (item.get('repository') or {}).get('full_name')
            if full_name:
                self.candidate(full_name, 'commit_search', token_key)

    def from_accessible_repos(self, client: GitHubClient, token_key: str, limit: int) -> None:
        """List repositories visible to the token, most recently pushed first, until pushes predate --since.

        Only used for narrowly scoped tokens: with more than `limit` recently pushed repositories the token
        is organisation-wide and checking each one would be slow noise.
        """
        url = '/user/repos'
        params = {'sort': 'pushed', 'direction': 'desc', 'per_page': 100}
        found: list[dict] = []
        while url:
            status, headers, payload = client.get(url, params)
            if status != 200 or not isinstance(payload, list):
                self.warnings.append(f'[{token_key}] listing accessible repositories failed: {describe_error(status, payload)}')
                return
            for repo in payload:
                pushed = repo.get('pushed_at')
                if pushed and parse_day(pushed.rstrip('Z')) < self.since:
                    url = None
                    break
                found.append(repo)
                if len(found) > limit:
                    self.warnings.append(f'[{token_key}] can access more than {limit} recently pushed repositories '
                                         '(organisation-wide); its repository list was not used')
                    return
            else:
                match = re.search(r'<([^>]+)>;\s*rel="next"', headers.get('Link', ''))
                url, params = (match.group(1), None) if match else (None, None)
        for repo in found:
            self.candidate(repo['full_name'], 'accessible_recently_pushed', token_key, default_branch=repo.get('default_branch'),
                           fork=repo.get('fork'), archived=repo.get('archived'))

    def pr_base_branches(self, client_for, prs: list[dict]) -> None:
        for pr in prs:
            repo = self.repos.get(pr['repo'].lower())
            client = client_for(pr['repo'])
            if not repo or not client:
                continue
            status, _, payload = client.get(f"/repos/{pr['repo']}/pulls/{pr['number']}")
            if status == 200:
                repo['pr_base_branches'].add(payload['base']['ref'])
                repo.setdefault('default_branch', (payload['base'].get('repo') or {}).get('default_branch'))

    def verify(self, client_for) -> None:
        for repo in self.repos.values():
            client = client_for(repo['name'])
            if not client:
                repo['verified'] = None
                repo['verify_error'] = 'no token for this owner'
                continue
            params = {'author': self.username, 'since': iso(self.since), 'until': iso(self.until), 'per_page': 1}
            status, _, payload = client.get(f"/repos/{repo['name']}/commits", params)
            if status == 200:
                repo['verified'] = bool(payload)
                repo['latest_commit'] = payload[0]['commit']['author']['date'] if payload else None
                if not payload and any(k in repo['sources'] for k in ('pr_search', 'graphql_prs')):
                    # No default-branch commits, but PR activity: --fetch-pr-commits may still find commits
                    repo['verified'] = 'pr_activity_only'
            elif status == 409:  # empty repository
                repo['verified'] = False
            else:
                repo['verified'] = None
                repo['verify_error'] = describe_error(status, payload)
            if 'default_branch' not in repo:
                status, _, info = client.get(f"/repos/{repo['name']}")
                if status == 200:
                    repo.update(default_branch=info.get('default_branch'), fork=info.get('fork'), archived=info.get('archived'))


def main() -> None:
    configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('username')
    parser.add_argument('--since', required=True)
    parser.add_argument('--until', help='Default: now')
    parser.add_argument('--root')
    parser.add_argument('--api-url', default=DEFAULT_API_URL)
    parser.add_argument('--max-repos', type=int, default=200, help='Cap on verified candidates (default 200)')
    parser.add_argument('--max-listed', type=int, default=100,
                        help='Use a token\'s accessible repositories only if at most this many were pushed since --since (default 100)')
    parser.add_argument('--max-prs', type=int, default=100, help='PRs inspected for target branches (default 100)')
    parser.add_argument('--extra-repos', default='', help='Comma-separated owner/repo list to verify as well (e.g. an existing config)')
    parser.add_argument('--ca-bundle')
    parser.add_argument('--no-verify-ssl', action='store_true')
    args = parser.parse_args()

    root = find_project_root(args.root)
    settings = load_settings(root) if root else {}
    tokens = parse_tokens(settings.get('GITHUB_TOKEN', ''))
    if not tokens:
        fail('No GITHUB_TOKEN in the environment or .env')
    context = ssl_context(settings, args.no_verify_ssl, args.ca_bundle)
    clients = {key: GitHubClient(token, args.api_url, context) for key, token in tokens.items()}

    def client_for(full_name: str) -> GitHubClient | None:
        owner = full_name.split('/')[0].lower()
        return clients.get(owner) or clients.get('*')

    since = parse_day(args.since)
    until = parse_day(args.until) if args.until else datetime.now(timezone.utc)
    discovery = Discovery(args.username, since, until)
    prs: list[dict] = []
    for key, client in clients.items():
        if not discovery.from_graphql(client, key):
            discovery.from_commit_search(client, key)
        prs.extend(discovery.from_pr_search(client, key, args.max_prs))
        discovery.from_accessible_repos(client, key, args.max_listed)

    for full_name in filter(None, (r.strip() for r in args.extra_repos.split(','))):
        discovery.candidate(full_name, 'given', 'n/a')

    if len(discovery.repos) > args.max_repos:
        # Keep candidates backed by search/contribution evidence first
        ranked = sorted(discovery.repos.items(), key=lambda kv: set(kv[1]['sources']) == {'accessible_recently_pushed'})
        discovery.warnings.append(f'{len(discovery.repos)} candidates; only {args.max_repos} were verified')
        discovery.repos = dict(ranked[:args.max_repos])
    discovery.pr_base_branches(client_for, prs[:args.max_prs])
    discovery.verify(client_for)

    # Unverified candidates from listing alone are noise; keep them only when another source points at them
    repos = [r for r in discovery.repos.values()
             if r.get('verified') or set(r['sources']) - {'accessible_recently_pushed'}]
    repos.sort(key=lambda r: (r.get('verified') is not True, r['name'].lower()))
    for repo in repos:
        repo['token_keys'] = sorted(repo['token_keys'])
        default = repo.get('default_branch')
        repo['pr_base_branches'] = sorted(b for b in repo['pr_base_branches'] if b != default)
        owner = repo['name'].split('/')[0].lower()
        repo['token_for_scraper'] = owner if owner in tokens else ('*' if '*' in tokens else None)
    result = {
        'username': args.username, 'since': iso(since), 'until': iso(until), 'api_url': args.api_url,
        'repositories': repos,
        'verified_count': sum(1 for r in repos if r.get('verified') is True),
        'pr_activity_only_count': sum(1 for r in repos if r.get('verified') == 'pr_activity_only'),
        'restricted_contributions': discovery.restricted,
        'warnings': discovery.warnings,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
