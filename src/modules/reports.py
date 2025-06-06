# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Handles the generation of reports in various formats (Markdown, Text, JSON)."""

from collections import defaultdict
import json
import logging
import os
from typing import Any

from github.Commit import Commit

from src.modules.api import CommitRecord

log = logging.getLogger(__name__)


class ReportGenerator:

    def __init__(self, output_path: str, commit_fields: list[str] | None = None) -> None:
        """Initialize the ReportGenerator.

        Args:
            output_path: Existing path to save the report
            commit_fields: List of fields to include in the commit output
        """
        os.makedirs(output_path, exist_ok=True)
        self.md_report_path = os.path.join(output_path, 'report.md')
        self.text_report_path = os.path.join(output_path, 'report.txt')
        self.json_report_path = os.path.join(output_path, 'report.json')
        self.commit_fields = commit_fields or ['date', 'url', 'message']

    def generate_reports(
        self,
        commit_records: list[CommitRecord],
        repo_descriptions: dict[str, str] | None = None,
        report_formats: list[str] | None = None,
    ) -> None:
        """Generate reports of commits grouped by repository in specified formats.

        Args:
            commit_records: List of commit records containing repository name and Commit object
            repo_descriptions: Dictionary mapping repository names to descriptions
            report_formats: List of report formats to generate; options: 'markdown', 'text', 'json'
        """
        if repo_descriptions is None:
            repo_descriptions = {}
        if report_formats is None:
            report_formats = ['text']

        repos_count = len(set(record.repo_full_name for record in commit_records))
        log.info('Generating reports for %d commits across %d repositories', len(commit_records), repos_count)

        # Group commits by repository
        commits_by_repo_full_name: dict[str, list[Commit]] = defaultdict(list)
        for record in commit_records:
            commits_by_repo_full_name[record.repo_full_name].append(record.commit)

        # Sort commits by date within each repository (oldest first)
        for repo_full_name in commits_by_repo_full_name:
            commits_by_repo_full_name[repo_full_name].sort(key=lambda c: c.commit.author.date)

        # Generate requested report formats
        if 'markdown' in report_formats:
            self._generate_markdown_report(repo_descriptions, commits_by_repo_full_name)
            log.info('Markdown report generated at %s', self.md_report_path)
        if 'text' in report_formats:
            self._generate_text_report(repo_descriptions, commits_by_repo_full_name)
            log.info('Text report generated at %s', self.text_report_path)
        if 'json' in report_formats:
            self._generate_json_report(repo_descriptions, commits_by_repo_full_name)
            log.info('JSON report generated at %s', self.json_report_path)

    def _generate_markdown_report(
        self,
        repo_descriptions: dict[str, str],
        commits_by_repo_full_name: dict[str, list[Commit]],
    ) -> None:
        """Generate a markdown report of commits grouped by repository.

        Args:
            repo_descriptions: Dictionary mapping repository names to descriptions
            commits_by_repo_full_name: Dictionary mapping repository names to commit lists
        """
        with open(self.md_report_path, 'w', encoding='utf-8') as f:
            # Create a set of all repositories from commits
            all_repos_full_names = set(commits_by_repo_full_name.keys())

            for repo_full_name in sorted(all_repos_full_names):
                if repo_full_name not in commits_by_repo_full_name:
                    continue

                f.write(f'## {repo_full_name}\n\n')

                # Add repository description if available
                if repo_full_name in repo_descriptions:
                    f.write(f'{repo_descriptions[repo_full_name]}\n\n')

                # Write commits
                for commit in commits_by_repo_full_name[repo_full_name]:
                    commit_data = self._build_commit_data(commit)
                    commit_json = json.dumps(commit_data, indent=2)
                    f.write('```json\n')
                    f.write(commit_json)
                    f.write('\n```\n\n')

                # Add a separator between repositories
                f.write('\n')

    def _generate_text_report(
        self,
        repo_descriptions: dict[str, str],
        commits_by_repo_full_name: dict[str, list[Commit]],
    ) -> None:
        """Generate a text report of commits grouped by repository.

        Args:
            repo_descriptions: Dictionary mapping repository names to descriptions
            commits_by_repo_full_name: Dictionary mapping repository names to commit lists
        """
        with open(self.text_report_path, 'w', encoding='utf-8') as f:
            # Create a set of all repositories from commits
            all_repos_full_names = set(commits_by_repo_full_name.keys())

            for repo_full_name in sorted(all_repos_full_names):
                if repo_full_name not in commits_by_repo_full_name:
                    continue

                f.write(f'- {repo_full_name}\n\n')

                # Add repository description if available
                if repo_full_name in repo_descriptions:
                    f.write(f'\t{json.dumps(repo_descriptions[repo_full_name])}\n\n')

                # Write commits
                for commit in commits_by_repo_full_name[repo_full_name]:
                    commit_data = self._build_commit_data(commit)
                    for key, value in commit_data.items():
                        f.write(f'\t{key}: {json.dumps(value)}\n')
                    f.write('\n')

    def _generate_json_report(
        self,
        repo_descriptions: dict[str, str],
        commits_by_repo_full_name: dict[str, list[Commit]],
    ) -> None:
        """Generate a JSON report of commits grouped by repository.

        Args:
            repo_descriptions: Dictionary mapping repository names to descriptions
            commits_by_repo_full_name: Dictionary mapping repository names to commit lists
        """
        report_data = []

        for repo_full_name, commits in commits_by_repo_full_name.items():
            repo_data: dict[str, Any] = {
                'name': repo_full_name,
                'description': repo_descriptions.get(repo_full_name, ''),
                'commits': [self._build_commit_data(commit) for commit in commits],
            }

            report_data.append(repo_data)

        with open(self.json_report_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2)

    def _build_commit_data(
        self,
        commit: Commit,
    ) -> dict[str, Any]:
        """Construct a commit_data dictionary from a Commit object based on the specified fields.

        Args:
            commit: A Commit object from the GitHub API

        Returns:
            A dictionary containing chosen commit data
        """
        commit_data: dict[str, Any] = {}
        if 'date' in self.commit_fields:
            commit_data['date'] = commit.commit.author.date.isoformat()
        if 'url' in self.commit_fields:
            commit_data['url'] = commit.html_url
        if 'message' in self.commit_fields:
            commit_data['message'] = commit.commit.message
        if 'sha' in self.commit_fields:
            commit_data['sha'] = commit.sha
        if 'stats' in self.commit_fields:
            commit_data['stats'] = {
                'additions': commit.stats.additions,
                'deletions': commit.stats.deletions,
                'total': commit.stats.total,
            }
        if 'files_changed' in self.commit_fields:
            commit_data['files_changed'] = [{
                'filename': f.filename,
                'status': f.status,
                'additions': f.additions,
                'deletions': f.deletions,
            } for f in commit.files]

        return commit_data
