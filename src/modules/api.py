# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Handles interactions with the GitHub API for fetching repository, commit, and PR data."""

from collections import defaultdict
from dataclasses import dataclass
import logging
import os
import sys
from datetime import datetime, timezone

from github import Github
from github.Commit import Commit
from github.Repository import Repository
from github.PullRequest import PullRequest

log = logging.getLogger(__name__)


@dataclass
class CommitRecord:
    """Holds a reference to a repo full name and a commit object."""
    repo_full_name: str
    commit: Commit


class GitHubAPI:

    def __init__(self, token: str | None = None, ssl_verify: bool | str = True) -> None:
        """Initialize GitHub API client with token and SSL verification options.

        Args:
            token: GitHub API token
            ssl_verify: SSL verification mode - True (default), False, or path to CA bundle
        """
        self.token = token or os.environ.get('GITHUB_TOKEN')
        if not self.token:
            raise ValueError('GitHub token is required. Set GITHUB_TOKEN environment variable or pass token parameter')

        # Use environment variables if not explicitly provided
        if ssl_verify is True:
            # Check for CA bundle environment variables
            ca_bundle = os.environ.get('REQUESTS_CA_BUNDLE') or os.environ.get('SSL_CERT_FILE')
            if (ca_bundle and os.path.exists(ca_bundle)):
                ssl_verify = ca_bundle

        # Initialize GitHub client with proper SSL config
        self.client = Github(self.token, verify=ssl_verify)
        log.debug('GitHub API client initialized (SSL verify: %s)', ssl_verify)

    def fetch_repo_by_full_name(self, repo_full_name: str) -> Repository | None:
        """Fetch a repository by its full name (owner/repo).

        Args:
            repo_full_name: Full name of the repository (e.g., 'owner/repo')

        Returns:
            Repository object if found, None otherwise
        """
        log.info('Fetching repository: %s', repo_full_name)
        try:
            repo: Repository = self.client.get_repo(repo_full_name)
            log.debug('Fetched repository: %s', repo_full_name)
            return repo
        except Exception as e:  # pylint: disable=W0718:broad-exception-caught
            log.error('Error fetching repository %s: %s', repo_full_name, str(e))
            return None

    def fetch_repo_commit_records(
        self, repo: Repository, username: str, since: datetime,
        include_merge_commits: bool = False, exclude_pr_merge_commits: bool = False,
    ) -> list[CommitRecord]:
        """Fetch all commit records for a repository, with optional filters.

        Args:
            repo: GitHub repository object
            username: Filter commits by this author
            since: Only commits after this date
            include_merge_commits: Whether to include merge commits
            exclude_pr_merge_commits: Whether to exclude PR merge commits

        Returns:
            List of commit records matching the criteria
        """
        log.info('Fetching direct commits by %s in %s since %s', username, repo.full_name, since.isoformat())
        try:
            commits: list[Commit] = list(repo.get_commits(author=username, since=since))
            if not include_merge_commits:
                commits = [c for c in commits if len(c.parents) <= 1]
            if exclude_pr_merge_commits:
                commits = [c for c in commits if c.commit.committer.name != 'GitHub']
            log.debug('Fetched %s commits in repository %s since %s', len(commits), repo.full_name, since.isoformat())
            return [CommitRecord(repo.full_name, c) for c in commits]
        except Exception as e:  # pylint: disable=W0718:broad-exception-caught
            log.error('Error fetching commits for %s: %s', repo.full_name, str(e))
            return []

    def fetch_user_pull_requests_in_repos(self, repos: list[Repository], username: str, since: datetime) -> list[PullRequest]:
        """Fetch user pull requests (open or closed/merged) updated/closed/merged after 'since'.

        Args:
            repos: List of repository objects to search in
            username: GitHub username to find pull requests for
            since: Only include pull requests updated after this datetime

        Returns:
            List of pull requests matching the criteria
        """
        all_pull_requests: list[PullRequest] = []
        for repo in repos:
            log.info('Fetching pull requests by %s in %s updated after %s', username, repo.full_name, since.isoformat())
            try:
                # We sort by updated so we can stop once we cross the date threshold
                for pr in repo.get_pulls(state='all', sort='updated', direction='desc'):
                    # `pr.updated_at` should never be None based on GitHub API docs
                    # https://docs.github.com/en/rest/commits/commits?apiVersion=2022-11-28#list-pull-requests
                    assert pr.updated_at is not None, \
                        f'Pull request updated_at is None for PR #{pr.number} in {repo.full_name}'
                    if pr.updated_at < since.replace(tzinfo=timezone.utc):
                        break
                    if pr.user.login == username:
                        all_pull_requests.append(pr)
                log.debug(
                    'Fetched %d pull requests by %s in %s updated after %s',
                    len(all_pull_requests), username, repo.full_name, since.isoformat())

            except Exception as e:  # pylint: disable=W0718:broad-exception-caught
                log.error('Error fetching %s pull requests for %s: %s', username, repo.full_name, str(e))

        return all_pull_requests

    def fetch_user_commit_records_in_pr_after_date(self, pr: PullRequest, username: str, since: datetime) -> list[CommitRecord]:
        """Return user commit records in the given PR that were committed after 'since'.

        Args:
            pr: PullRequest object to search in
            username: GitHub username to filter commits
            since: Only include commits after this datetime

        Returns:
            List of commit records matching the criteria
        """
        log.info('Fetching relevant %s commits in PR #%d in %s', username, pr.number, pr.base.repo.full_name)
        user_commit_records: list[CommitRecord] = []
        try:
            for commit in pr.get_commits():
                if commit.author and commit.author.login == username:
                    if commit.commit.author.date >= since.replace(tzinfo=timezone.utc):
                        # Ignore merge commits
                        if len(commit.parents) > 1:
                            continue
                        user_commit_records.append(CommitRecord(pr.base.repo.full_name, commit))
            log.debug('Fetched %d commits by %s in PR #%d in %s', len(user_commit_records), username, pr.number, pr.base.repo.full_name)

        except Exception as e:  # pylint: disable=W0718:broad-exception-caught
            log.error('Error fetching commits for PR #%d: %s', pr.number, str(e))

        return user_commit_records


def parse_token_map(token_str: str) -> dict[str, str]:
    """Parse a token string into a dictionary of owner tokens.

    Args:
        token_str: Token string (either a single token or a map in owner:token format)

    Returns:
        Dictionary of owner tokens or a single default token under '_default'
    """
    tokens: dict[str, str] = {}
    for pair in token_str.split(','):
        if ':' in pair:
            owner, token = pair.split(':', 1)
            tokens[owner.strip().lower()] = token.strip()
        else:
            # Use a placeholder key for the default token
            tokens['_default'] = pair.strip()
    return tokens


def group_repos_by_owner(repo_full_names: list[str]) -> dict[str, list[str]]:
    """Group repository full names by their owner.

    Args:
        repo_full_names: List of repository full names (format: owner/repo)

    Returns:
        Dictionary mapping owner names to lists of repository full names
    """
    grouped_repos: dict[str, list[str]] = defaultdict(list)
    for repo_full_name in repo_full_names:
        try:
            owner, _ = repo_full_name.split('/', 1)
            owner = owner.lower()
            grouped_repos[owner].append(repo_full_name)
        except ValueError:
            log.warning('Invalid repository format skipped: %s', repo_full_name)
    return grouped_repos


def initialize_apis(token_map: dict[str, str], ssl_verify: bool | str) -> dict[str, GitHubAPI]:
    """Initialize GitHub API clients for each owner.

    Args:
        token_map: Dictionary of owner tokens (key '_default' for single token)
        ssl_verify: SSL verification mode

    Returns:
        Dictionary of GitHubAPI clients keyed by owner (lowercase)
    """
    apis: dict[str, GitHubAPI] = {}
    default_token = token_map.pop('_default', None)
    default_api = None

    if default_token:
        try:
            default_api = GitHubAPI(token=default_token, ssl_verify=ssl_verify)
            owner_login = default_api.client.get_user().login.lower()
            apis[owner_login] = default_api
            log.info('Initialized default API client for user: %s', owner_login)
        except Exception as e:  # pylint: disable=W0718:broad-exception-caught
            log.error('Failed to initialize default GitHub API client: %s', str(e))
            sys.exit(1)  # Exit if default token is invalid

    for owner, token in token_map.items():
        if owner in apis:
            log.warning('Token for owner %s already provided by default token, skipping specific token.', owner)
            continue
        try:
            api = GitHubAPI(token=token, ssl_verify=ssl_verify)
            # Verify the token works and belongs to the expected owner (optional but good practice)
            api_user_login = api.client.get_user().login.lower()
            log.info('Initialized API client for owner: %s (token user: %s)', owner, api_user_login)
            # We store the API client under the owner name specified in the map
            apis[owner] = api
        except Exception as e:  # pylint: disable=W0718:broad-exception-caught
            log.error('Failed to initialize GitHub API client for owner %s: %s', owner, str(e))
            # TODO: Decide if we should exit or just skip this owner
            # For now, let's skip and log the error.
            # sys.exit(1)

    # If only a default token was provided, ensure it's available for lookups
    # This handles the case where the repo list might contain owners not explicitly mapped
    if default_api and '_default' not in apis:  # Add a reference for generic lookup if needed
        apis['_default'] = default_api

    return apis


def fetch_repositories(apis: dict[str, GitHubAPI], repos_by_owner: dict[str, list[str]]) -> list[Repository]:
    """Fetch repository objects from GitHub using appropriate API clients.

    Args:
        apis: Dictionary of GitHubAPI clients keyed by owner or '_default'.
        repos_by_owner: Dictionary mapping owners to repository names.

    Returns:
        List of Repository objects. Exits if an API client is missing for an owner.
    """
    repos: list[Repository] = []
    default_api = apis.get('_default')

    for owner, owner_repos in repos_by_owner.items():
        api = apis.get(owner) or default_api  # Fallback to default API if specific owner API not found
        if not api:
            log.error('No API client found for owner %s and no default token provided.', owner)
            # Consider raising an exception instead of sys.exit for better testability/reusability
            sys.exit(1)

        log.info('Using API client for owner %s (or default)', owner)
        for repo_full_name in owner_repos:
            try:
                if repo := api.fetch_repo_by_full_name(repo_full_name):
                    repos.append(repo)
                else:
                    log.warning('Could not fetch repository: %s', repo_full_name)
            except Exception as e:  # pylint: disable=W0718:broad-exception-caught
                log.error('Unexpected error fetching repository %s: %s', repo_full_name, str(e))
    return repos


def process_commits_and_prs(
    repos: list[Repository], apis: dict[str, GitHubAPI], username: str, since_date: datetime, fetch_pr_commits: bool, include_merge_commits: bool
) -> list[CommitRecord]:
    """Process commits and pull requests for the given repositories using appropriate API clients.

    Args:
        repos: List of Repository objects.
        apis: Dictionary of GitHubAPI clients keyed by owner or '_default'.
        username: GitHub username.
        since_date: Date to filter commits and PRs.
        fetch_pr_commits: Whether to include PR commits.
        include_merge_commits: Whether to include merge commits.

    Returns:
        Lists of direct commit records and PR commit records. Exits if an API client is missing.
    """
    default_api = apis.get('_default')

    def get_api_for_repo(repo: Repository) -> GitHubAPI:
        owner_name = repo.owner.login.lower()
        api = apis.get(owner_name) or default_api
        if not api:
            log.error('No API client found for repository owner %s and no default token provided.', owner_name)
            sys.exit(1)
        return api

    all_commit_records: list[CommitRecord] = []
    all_pull_requests: list[PullRequest] = []
    processed_repo_names: set[str] = set()  # Track processed repos to avoid duplicates if PRs span repos

    for repo in repos:
        if repo.full_name in processed_repo_names:
            continue
        processed_repo_names.add(repo.full_name)

        api_client = get_api_for_repo(repo)
        log.info("Processing repository: %s with API for owner %s", repo.full_name, repo.owner.login.lower())

        # Fetch direct commits
        commits = api_client.fetch_repo_commit_records(
            repo, username, since_date,
            include_merge_commits=include_merge_commits, exclude_pr_merge_commits=fetch_pr_commits)
        all_commit_records.extend(commits)

        # Fetch PRs if requested (only need to do this once per repo)
        if fetch_pr_commits:
            prs = api_client.fetch_user_pull_requests_in_repos([repo], username, since_date)
            all_pull_requests.extend(prs)

    all_pr_commit_records: list[CommitRecord] = []
    if fetch_pr_commits:
        log.info("Processing %d Pull Requests for commits...", len(all_pull_requests))
        processed_pr_numbers: set[tuple[str, int]] = set()  # Track processed PRs (repo_name, pr_number)
        for pr in all_pull_requests:
            repo_full_name = pr.base.repo.full_name
            pr_key = (repo_full_name, pr.number)
            if pr_key in processed_pr_numbers:
                continue
            processed_pr_numbers.add(pr_key)

            pr_api = get_api_for_repo(pr.base.repo)  # Get API client based on PR's base repo owner
            log.info("Processing PR #%d in %s with API for owner %s", pr.number, repo_full_name, pr.base.repo.owner.login.lower())
            pr_commit_records = pr_api.fetch_user_commit_records_in_pr_after_date(pr, username, since_date)
            all_pr_commit_records.extend(pr_commit_records)

    # Deduplicate commit records (same commit might appear directly and via PR)
    unique_commit_records: dict[str, CommitRecord] = {}
    for record in all_commit_records + all_pr_commit_records:
        # Use commit SHA as the unique key
        if record.commit.sha not in unique_commit_records:
            unique_commit_records[record.commit.sha] = record

    final_commit_list = list(unique_commit_records.values())
    log.info("Total unique commit records found: %d", len(final_commit_list))

    return final_commit_list
