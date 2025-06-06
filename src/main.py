# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Main command-line interface for the project.

This script orchestrates the fetching of GitHub contributions (commits and PRs)
for a specified user, filters them by date and repository, and generates
reports and diffs.
"""

import argparse
from datetime import datetime
import logging
import logging.config
import os
import sys
import yaml

from src.modules.api import (
    parse_token_map, initialize_apis, group_repos_by_owner,
    fetch_repositories, process_commits_and_prs,
)
from src.modules.diff import DiffGenerator
from src.modules.metadata import save_metadata
from src.modules.reports import ReportGenerator

log = logging.getLogger(__name__)


def setup_logging(config_path: str = 'logging.yaml') -> None:
    """Set up logging configuration from YAML file.

    Args:
        config_path: Path to the YAML logging configuration file
    """
    try:
        if os.path.exists(config_path):
            with open(config_path, encoding='utf-8') as f:
                config = yaml.safe_load(f.read())
            logging.config.dictConfig(config)
        else:
            logging.basicConfig(level=logging.INFO)
            logging.warning('Logging config file %s not found, using basic configuration', config_path)
    except Exception as e:  # pylint: disable=W0718:broad-exception-caught
        logging.basicConfig(level=logging.INFO)
        logging.error('Failed to load logging configuration: %s', str(e))


def parse_repo_list(repos_str: str) -> list[str]:
    """Parse a comma-separated list of repositories.

    Args:
        repos_str: Comma-separated string of repository names (format: owner/repo)

    Returns:
        List of repository names
    """
    if not repos_str:
        return []
    return [repo.strip() for repo in repos_str.split(',') if repo.strip()]


def parse_date(date_str: str) -> datetime:
    """Parse a date string into a datetime object.

    Supported formats: YYYY-MM-DD, YYYY-MM-DD HH:MM:SS.

    Args:
        date_str: Date string to parse

    Returns:
        Datetime object representing the input date
    """
    formats = [
        '%Y-%m-%d',
        '%Y-%m-%d %H:%M:%S'
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    raise ValueError(f'Unsupported date format: {date_str}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS')


def validate_args(args: argparse.Namespace) -> tuple[datetime, bool | str]:
    """Validate and process command-line arguments related to date and SSL.

    Args:
        args: Parsed command-line arguments

    Returns:
        A tuple containing the since_date and SSL verification mode
    """
    # Parse since date
    try:
        since_date = parse_date(args.since)
        if since_date > datetime.now():
            raise ValueError('Since date cannot be in the future')
    except ValueError as e:
        log.error(str(e))
        sys.exit(1)

    # Determine SSL verification mode
    ssl_verify: bool | str = True
    if args.no_verify_ssl:
        ssl_verify = False
        log.warning('SSL verification disabled! This is not recommended for production use')
    elif args.ca_bundle:
        if not os.path.exists(args.ca_bundle):
            log.error('Specified CA bundle file does not exist: %s', args.ca_bundle)
            sys.exit(1)
        ssl_verify = args.ca_bundle
        log.info('Using CA bundle: %s', args.ca_bundle)

    return since_date, ssl_verify


def main() -> None:
    """Main entry point for the script."""
    setup_logging()  # Set up logging with YAML configuration

    parser = argparse.ArgumentParser(description='GHContribScraperReportGen')
    parser.add_argument('username', help='GitHub username to scan for contributions')
    parser.add_argument('--since', required=True, help='Only include contributions after this date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--token', help='GitHub Personal Access Token or a map of owner tokens (comma-separated format: owner:token,owner2:token2)')
    parser.add_argument('--repositories', help='Comma-separated list of repositories (format: owner/repo)')
    parser.add_argument('--output', default='output', help='Output directory')
    parser.add_argument('--ca-bundle', help='Path to SSL CA bundle file')
    parser.add_argument('--no-verify-ssl', action='store_true', help='Disable SSL verification (not recommended)')
    parser.add_argument('--fetch-pr-commits', action='store_true', help='Fetch commits associated with user pull requests (may increase API usage)')
    parser.add_argument('--include-merge-commits', action='store_true', help='Include merge commits in the output (often excluded by default)')
    parser.add_argument(
        '--commit-fields',
        nargs='+',
        choices=(choices := ['date', 'url', 'message', 'sha', 'stats', 'files_changed']),
        default=(default := ['date', 'url', 'message']),
        help=f'List of commit fields to include in reports. Options: {", ".join(choices)}. Default: {", ".join(default)}',
    )
    parser.add_argument(
        '--report-formats',
        nargs='+',
        choices=(choices := ['text', 'markdown', 'json']),
        default=(default := ['text']),
        help=f'List of report formats to generate. Options: {", ".join(choices)}. Default: {", ".join(default)}',
    )

    parser.add_argument(
        '--limit-download-diffs',
        nargs=2,
        type=int,
        metavar=('LIMIT_FILES', 'LIMIT_LINES_CHANGED'),
        default=(30, 3000),
        help='Limit downloading diffs for commits exceeding file count or lines changed thresholds',
    )

    args = parser.parse_args()

    if not args.username:
        parser.error('Username is required.')  # Argparse handles exit

    since_date, ssl_verify = validate_args(args)

    # Parse token(s)
    token_str = args.token or os.environ.get('GITHUB_TOKEN', '')
    if not token_str:
        log.error('GitHub token is required. Set GITHUB_TOKEN environment variable or pass --token parameter')
        sys.exit(1)
    token_map = parse_token_map(token_str)

    # Initialize GitHub API clients
    apis = initialize_apis(token_map, ssl_verify)
    if not apis:
        log.error('Failed to initialize any GitHub API clients. Please check token(s)')
        sys.exit(1)

    # Parse repositories
    repo_full_names_str = args.repositories or os.environ.get('GITHUB_REPOSITORIES', '')
    repo_full_names: list[str] = parse_repo_list(repo_full_names_str)
    if not repo_full_names:
        log.error('No repositories specified. Use --repositories or set GITHUB_REPOSITORIES environment variable')
        sys.exit(1)

    # Group repositories by owner
    repos_by_owner = group_repos_by_owner(repo_full_names)

    # Create output tree and save metadata
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = os.path.join(args.output, timestamp)
    os.makedirs(output_path, exist_ok=True)
    save_metadata(output_path, args.username, repo_full_names, since_date)

    # Fetch repositories
    repos = fetch_repositories(apis, repos_by_owner)
    if not repos:
        log.error('No valid repositories could be accessed. Check repository names and token permissions. Exiting')
        sys.exit(1)

    # Process commits and PRs
    all_unique_commit_records = process_commits_and_prs(
        repos, apis, args.username, since_date, args.fetch_pr_commits, args.include_merge_commits,
    )

    if not all_unique_commit_records:
        log.warning('No relevant commit contributions found for user %s since %s in the specified repositories', args.username, since_date.date())
        sys.exit(0)

    # Extract repo descriptions for reports
    repo_descriptions = {repo.full_name: repo.description for repo in repos if repo.description}

    # Generate reports
    report_generator = ReportGenerator(output_path, commit_fields=args.commit_fields)
    report_generator.generate_reports(
        all_unique_commit_records,
        repo_descriptions=repo_descriptions,
        report_formats=args.report_formats,
    )

    # Save commit diffs
    diff_generator = DiffGenerator(
        output_path,
        args.limit_download_diffs[0],
        args.limit_download_diffs[1],
    )
    diff_generator.save_commit_diffs(all_unique_commit_records)

    log.info('Completed successfully. Output generated in: %s', output_path)


if __name__ == '__main__':
    main()
