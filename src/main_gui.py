# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Provides a NiceGUI-based graphical user interface for the project."""

import asyncio
from datetime import datetime
import os
import re
import sys
import subprocess

from nicegui import ui


def launch_interface() -> None:

    GITHUB_REPOSITORIES = os.environ.get('GITHUB_REPOSITORIES', '')
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')

    proc_ref: dict[str, subprocess.Popen | None] = {'proc': None}

    async def run_tool() -> None:
        if proc_ref['proc'] is not None:
            return
        run_btn.props('disabled')
        abort_btn.props(remove='disabled')

        os.environ['GITHUB_REPOSITORIES'] = ','.join([r.strip() for r in repositories.value.splitlines() if r.strip()]) or GITHUB_REPOSITORIES
        os.environ['GITHUB_TOKEN'] = ','.join([t.strip() for t in token_map.value.splitlines() if t.strip()]) or GITHUB_TOKEN

        cmd = [
            sys.executable, '-m', 'src.main',
            username.value, '--since', since.value,
            '--output', output_dir.value,
        ]
        if commit_fields.value:
            cmd.extend(['--commit-fields'] + commit_fields.value)
        if report_formats.value:
            cmd.extend(['--report-formats'] + report_formats.value)
        if fetch_pr.value:
            cmd.append('--fetch-pr-commits')
        if include_merge.value:
            cmd.append('--include-merge-commits')

        cmd.extend([
            '--limit-download-diffs',
            max_files.value,
            max_lines_changed.value,
        ])

        try:
            proc_sync = await asyncio.to_thread(
                lambda: subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
                )
            )
            proc_ref['proc'] = proc_sync

            while True:
                if not proc_sync.stdout:
                    break
                raw = await asyncio.to_thread(proc_sync.stdout.readline)
                if not raw:
                    break
                log_output.content += raw.decode()
                log_output.update()
            await asyncio.to_thread(proc_sync.wait)

        finally:
            proc_ref['proc'] = None
            run_btn.props(remove='disabled')
            abort_btn.props('disabled')

    def abort_tool() -> None:
        if proc_ref['proc']:
            proc_ref['proc'].kill()

    def clear_output() -> None:
        log_output.content = ''

    def validate_username(value: str) -> str | None:
        if not value.strip():
            return 'Username cannot be empty'
        if not re.match(r'^[a-zA-Z0-9-]+$', value):
            return 'Username can only contain alphanumeric characters or dashes'
        return None

    def validate_repositories(value: str) -> str | None:
        # Username may only contain alphanumeric characters or single hyphens, and cannot begin or end with a hyphen.
        # The repository name can only contain ASCII letters, digits, and the characters ., -, and _.
        if not GITHUB_REPOSITORIES and not value.strip():
            return 'Repositories cannot be empty'
        repos = [r.strip() for r in value.splitlines() if r.strip()]
        for repo in repos:
            if not re.match(r'^[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*\/[a-zA-Z0-9_.-]+$', repo):
                return f'Invalid repository format: {repo}'
        return None

    def validate_token_map(value: str) -> str | None:
        # Username may only contain alphanumeric characters or single hyphens, and cannot begin or end with a hyphen.
        # The token name can probably only contain ASCII letters, digits, and underscores.
        if not GITHUB_TOKEN and not value.strip():
            return 'Token map cannot be empty'
        token_map = [t.strip() for t in value.splitlines() if t.strip()]
        for token in token_map:
            # Allow single token (no colon) or owner:token pairs
            if not re.match(r'^[a-zA-Z0-9_]+$|^[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*:[a-zA-Z0-9_]+$', token):
                return f'Invalid token or owner:token format: {token}'
        return None

    def validate_date(value: str) -> str | None:
        if not value.strip():
            return 'Date cannot be empty'
        try:
            date = datetime.strptime(value, '%Y-%m-%d')
        except ValueError:
            return 'Invalid date format'
        if date > datetime.now():
            return 'Date cannot be in the future'
        return None

    def validate_output_dir(value: str) -> str | None:
        if not value.strip():
            return 'Output directory cannot be empty'
        if not re.match(r'^[a-zA-Z0-9_.-]+$', value):
            return 'Output directory should probably only contain alphanumeric characters, underscores, dashes, or dots'
        return None

    def validate_max_files(value: str) -> str | None:
        if not value.strip():
            return 'Max diff files per commit cannot be empty'
        if not value.isdigit():
            return 'Max diff files per commit must be an integer'
        return None

    def validate_max_lines_changed(value: str) -> str | None:
        if not value.strip():
            return 'Max diff lines changed per commit cannot be empty'
        if not value.isdigit():
            return 'Max diff lines changed per commit must be an integer'
        return None

    def update_run_button() -> None:
        valid = not any([
            validate_username(username.value),
            validate_repositories(repositories.value),
            validate_token_map(token_map.value),
            validate_date(since.value),
            validate_max_files(max_files.value),
            validate_max_lines_changed(max_lines_changed.value),
        ])
        if valid:
            run_btn.props(remove='disabled')
        else:
            run_btn.props('disabled')

    ui.markdown('# GHContribScraperReportGen')

    with ui.row().style('align-items: start; justify-content: center; width: 100%; padding: 1rem; flex-wrap: nowrap;'):

        with ui.column().style('width: 50%; max-width: 50%; gap: 1rem;'):
            ui.markdown('## Input')

            username = ui.input('Username', validation=validate_username)\
                .style('width: 100%').props('autocorrect=off').props('spellcheck=false')
            repositories = ui.textarea(
                'Repositories (one per line)' + ('. If left empty, env var `GITHUB_REPOSITORIES` will be used' if GITHUB_REPOSITORIES else ''),
                validation=validate_repositories,
                placeholder='owner/repo',
            ).style('width: 100%').props('autocorrect=off').props('spellcheck=false')
            token_map = ui.textarea(
                'Owner:Token pairs (one per line) or a token' + ('. If left empty, env var `GITHUB_TOKEN` will be used' if GITHUB_TOKEN else ''),
                validation=validate_token_map,
                placeholder='owner:token or token',
            ).style('width: 100%').props('autocorrect=off').props('spellcheck=false')
            since = ui.input('Since Date (YYYY-MM-DD)', validation=validate_date, value=f'{datetime.now().strftime("%Y-%m-01")}')\
                .style('width: 100%')

            commit_fields = ui.select(
                ['date', 'url', 'message', 'sha', 'stats', 'files_changed'],
                label='Commit Fields',
                value=['date', 'url', 'message'],
                multiple=True,
            ).style('width: 100%')
            report_formats = ui.select(
                ['text', 'markdown', 'json'],
                label='Report Formats',
                value=['text'],
                multiple=True,
            ).style('width: 100%')
            fetch_pr = ui.checkbox('Fetch PR Commits').style('width: 100%')
            include_merge = ui.checkbox('Include Merge Commits').style('width: 100%')
            output_dir = ui.input('Output Directory', validation=validate_output_dir, value='output')\
                .style('width: 100%').props('autocorrect=off').props('spellcheck=false')

            max_files = ui.input('Max diff files per commit', validation=validate_max_files, value='30')\
                .style('width: 100%').props('autocorrect=off').props('spellcheck=false')

            max_lines_changed = ui.input('Max diff lines changed per commit', validation=validate_max_lines_changed, value='3000')\
                .style('width: 100%').props('autocorrect=off').props('spellcheck=false')

            run_btn = ui.button('Run', on_click=run_tool).props('primary').props('disabled')
            abort_btn = ui.button('Abort', on_click=abort_tool).props('disabled').props('color=red')
            ui.button('Clear Output', on_click=clear_output).props('color=secondary')

            # Update fields triggering validation check
            # NOTE: Don't disable run button on invalid output_dir
            for field in [username, repositories, token_map, since, max_files, max_lines_changed]:
                # Call validate() on interaction and update button state
                field.on('blur', lambda _, f=field: f.validate() and update_run_button())  # type: ignore
                # Trigger validate() initially to show potential errors on load
                field.validate()
            # Set initial button state based on initial validation results
            update_run_button()

        with ui.column().style('width: 50%; max-width: 50%;'):
            ui.markdown('## Output')
            log_output = ui.code(language='text').style('overflow: auto; width: 100%; padding: 1rem;')


def main() -> None:
    ui.run(launch_interface, title='GHContribScraperReportGen')


if __name__ in {"__main__", "__mp_main__"}:
    main()
