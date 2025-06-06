# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Handles the generation and saving of commit diffs."""

import logging
import os

from src.modules.api import CommitRecord

log = logging.getLogger(__name__)


class DiffGenerator:

    def __init__(
        self,
        output_path: str,
        limit_files: int = 30,
        limit_lines_changed: int = 3000
    ) -> None:
        """Initialize the DiffGenerator to handle saving data and generating directories.

        Args:
            output_path: Existing path to save the diffs
            limit_files: Maximum number of files per commit to download
            limit_lines_changed: Maximum total lines changed per commit to download
        """
        self.limit_files = limit_files
        self.limit_lines_changed = limit_lines_changed
        self.files_dir = os.path.join(output_path, 'commits')
        os.makedirs(self.files_dir)

    def save_commit_diffs(self, commit_records: list[CommitRecord]) -> None:
        """Save diffs for all commits using the commit records.

        Args:
            commit_records: List of commit records
        """
        log.info('Downloading and saving diffs for %d commits', len(commit_records))
        saved_count = 0

        for record in commit_records:
            # Skip if the commit exceeds the line change limit
            if record.commit.stats.total > self.limit_lines_changed:
                log.info(
                    'Skipping commit %s in %s: exceeds limit (%d lines changed)',
                    record.commit.sha,
                    record.repo_full_name,
                    self.limit_lines_changed
                )
                continue

            # Skip if the commit exceeds the file limit
            # NOTE: Commit.files is a paginated list
            num_files = 0
            file_limit_exceeded = False
            for file in record.commit.files:
                num_files += 1

                if num_files > self.limit_files:
                    log.info(
                        'Skipping diff for commit %s in %s: exceeds limits (%d files)',
                        record.commit.sha,
                        record.repo_full_name,
                        self.limit_files,
                    )
                    file_limit_exceeded = True
                    break
            if file_limit_exceeded:
                continue

            repo_name = record.repo_full_name.split('/')[-1]  # Drop the owner part
            commit = record.commit
            if not repo_name or not commit.sha:
                log.warning('Skipping commit with missing repository or SHA')
                continue

            try:
                diff_path = os.path.join(self.files_dir, f'{commit.sha}.diff')

                with open(diff_path, 'w', encoding='utf-8') as f:
                    for file in commit.files:
                        f.write(f'File: {file.filename}\nStatus: {file.status}\nChanges: +{file.additions} -{file.deletions}\n')
                        if file.patch:
                            f.write(f'Patch:\n{file.patch}\n')
                        f.write('-' * 60 + '\n')

                saved_count += 1
                if saved_count % 10 == 0:
                    log.info('Downloaded %d/%d commit diffs...', saved_count, len(commit_records))
            except Exception as e:  # pylint: disable=W0718:broad-exception-caught
                log.error('Failed to save diff for commit %s: %s', commit.sha, str(e))

        if saved_count > 10:
            log.info('Downloaded %d/%d commit diffs...', saved_count, len(commit_records))
        else:
            log.debug('Successfully saved %d/%d commit diffs', saved_count, len(commit_records))
