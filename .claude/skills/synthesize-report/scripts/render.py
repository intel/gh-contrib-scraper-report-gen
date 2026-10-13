# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Validate synthesis.json against the run's report and render it to synthesis.html.

Usage: python render.py RUN_DIR [--synthesis PATH] [--template-dir DIR] [--out PATH] [--force] [--no-report]

By default every item must cite at least one commit from report.json; citations become links.
With --no-report (input was not report.json), items cite sources via "links" instead and
statistics come only from "extra_stats". Exit codes: 0 ok, 1 validation error, 3 output exists.
"""

import argparse
import html
import os
import re
import string
import sys
from urllib.parse import urlsplit

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__

from _common import configure_stdout, fail, index_commits, load_metadata, load_report, read_json, resolve_sha, run_date  # noqa: E402

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LABELS = {
    'period': 'Period',
    'statistics': 'Statistics',
    'repositories': 'Repositories',
    'commits': 'Commits',
    'lines': 'Lines changed',
    'files': 'Files touched',
}
MAX_COMMITS_PER_ITEM = 15
BLOCK_MARKER = re.compile(r'^<!-- block: (\w+) -->$', re.MULTILINE)


def load_blocks(path: str) -> dict[str, string.Template]:
    with open(path, encoding='utf-8') as f:
        content = f.read()
    parts = BLOCK_MARKER.split(content)
    # parts = [preamble, name1, body1, name2, body2, ...]
    return {parts[i]: string.Template(parts[i + 1].strip('\n')) for i in range(1, len(parts) - 1, 2)}


def inline(text: str) -> str:
    """Escape text, allowing `code` spans and **bold** outside of them (always well nested)."""
    out = []
    for i, part in enumerate(re.split(r'`([^`]+)`', text)):
        if i % 2:
            out.append(f'<code>{html.escape(part, quote=False)}</code>')
        else:
            pieces = re.split(r'\*\*(.+?)\*\*', part)
            out.extend(f'<strong>{html.escape(p, quote=False)}</strong>' if j % 2 else html.escape(p, quote=False)
                       for j, p in enumerate(pieces))
    return ''.join(out)


def safe_url(url) -> bool:
    if not isinstance(url, str) or re.search(r'[\s\x00-\x1f\x7f]', url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ('http', 'https') and bool(parts.netloc)


def as_list(value, field: str, errors: list[str]) -> list:
    """Return value as a list (None -> []), recording an error for any other type."""
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f'{field} must be a list')
        return []
    return value


class Renderer:

    def __init__(self, blocks: dict[str, string.Template]) -> None:
        self.blocks = blocks

    def block(self, block_name: str, /, **values: str) -> str:
        if block_name not in self.blocks:
            fail(f'Template block "{block_name}" missing from blocks.html')
        try:
            return self.blocks[block_name].substitute(**values)
        except (KeyError, ValueError) as e:
            fail(f'Template block "{block_name}" has an unknown placeholder: {e}')
            return ''


def text_list(value, field: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        errors.append(f'"{field}" must be a non-empty string or a list of non-empty strings')
        return []
    return value


def main() -> None:
    configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('run_dir')
    parser.add_argument('--synthesis', help='Path to synthesis.json (default: RUN_DIR/synthesis.json)')
    parser.add_argument('--template-dir', default=os.path.join(SKILL_DIR, 'templates'),
                        help='Directory with report.html and blocks.html (default: the skill templates)')
    parser.add_argument('--out', help='Output HTML path (default: RUN_DIR/synthesis.html)')
    parser.add_argument('--force', action='store_true', help='Overwrite an existing output file')
    parser.add_argument('--no-report', action='store_true', help='Do not read report.json; items cite "links"')
    parser.add_argument('--all-uncited', action='store_true', help='List every uncited commit (default: largest 40)')
    args = parser.parse_args()

    synthesis_path = args.synthesis or os.path.join(args.run_dir, 'synthesis.json')
    out_path = args.out or os.path.join(args.run_dir, 'synthesis.html')
    if os.path.exists(out_path) and not args.force:
        print(f'Output already exists: {out_path} (ask the user, then re-run with --force)', file=sys.stderr)
        sys.exit(3)
    try:
        synthesis = read_json(synthesis_path)
    except (OSError, ValueError) as e:
        fail(f'Cannot read {synthesis_path}: {e}')
    if not isinstance(synthesis, dict):
        fail(f'{synthesis_path} must contain a JSON object')

    repos = [] if args.no_report else load_report(args.run_dir)
    index = index_commits(repos)
    total_citable = sum(len(entries) for entries in index.values())
    repo_names = {r['name'] for r in repos}
    renderer = Renderer(load_blocks(os.path.join(args.template_dir, 'blocks.html')))
    with open(os.path.join(args.template_dir, 'report.html'), encoding='utf-8') as f:
        # Leading comments (license header) are template-only and not rendered
        page = string.Template(re.sub(r'\A(\s*<!--.*?-->)+\s*', '', f.read(), flags=re.DOTALL))

    errors: list[str] = []
    warnings: list[str] = []
    if synthesis.get('schema_version') != 1:
        errors.append('"schema_version" must be 1')
    title = synthesis.get('title')
    if not isinstance(title, str) or not title.strip():
        errors.append('"title" must be a non-empty string')
        title = ''
    grouping = synthesis.get('grouping', 'repository')
    if grouping not in ('repository', 'theme'):
        errors.append('"grouping" must be "repository" or "theme"')
    labels = dict(DEFAULT_LABELS)
    if isinstance(synthesis.get('labels'), dict):
        labels.update({k: v for k, v in synthesis['labels'].items() if isinstance(v, str)})

    cited: set[tuple[str, str]] = set()
    citation_counts: dict[tuple[str, str], int] = {}
    sections_html = []
    sections = synthesis.get('sections')
    if not isinstance(sections, list) or not sections:
        errors.append('"sections" must be a non-empty list')
        sections = []
    for s_idx, section in enumerate(sections):
        where = f'sections[{s_idx}]'
        if not isinstance(section, dict):
            errors.append(f'{where} must be an object')
            continue
        name = section.get('name')
        if not isinstance(name, str) or not name.strip():
            errors.append(f'{where}.name must be a non-empty string')
            continue
        if grouping == 'repository' and not args.no_report and name not in repo_names:
            errors.append(f'{where}.name "{name}" is not a repository in the report (grouping is "repository")')
        items = section.get('items')
        if not isinstance(items, list) or not items:
            errors.append(f'{where}.items must be a non-empty list')
            continue
        items_html = []
        for i_idx, item in enumerate(items):
            item_where = f'{where}.items[{i_idx}]'
            text = item.get('text') if isinstance(item, dict) else None
            if not isinstance(text, str) or not text.strip():
                errors.append(f'{item_where} must be an object with a non-empty "text"')
                continue
            links = []
            cited_here: set[tuple[str, str]] = set()
            refs_in = as_list(item.get('commits'), f'{item_where}.commits', errors)
            if args.no_report and refs_in:
                warnings.append(f'{item_where}: "commits" ignored with --no-report; use "links"')
                refs_in = []
            for ref in refs_in:
                entry, error = resolve_sha(ref, index, prefer_repo=name)
                if error:
                    errors.append(f'{item_where}: {error}')
                    continue
                repo, commit = entry
                if grouping == 'repository' and repo['name'] != name:
                    errors.append(f'{item_where}: commit {commit["short"]} belongs to {repo["name"]}, not {name}')
                key = (repo['name'], commit['sha'])
                if key not in cited_here:
                    cited_here.add(key)
                    citation_counts[key] = citation_counts.get(key, 0) + 1
                cited.add(key)
                if safe_url(commit.get('url')):
                    links.append((commit['short'], commit['url']))
                else:
                    links.append((commit['short'], None))
            for link in as_list(item.get('links'), f'{item_where}.links', errors):
                if not isinstance(link, dict) or not safe_url(link.get('url')) or not str(link.get('label', '')).strip():
                    errors.append(f'{item_where}: each link needs a "label" and an http(s) "url"')
                    continue
                links.append((str(link['label']), link['url']))
            if len(cited_here) > MAX_COMMITS_PER_ITEM:
                warnings.append(f'{item_where} cites {len(cited_here)} commits; split it into more specific items')
            if not links:
                errors.append(f'{item_where}: cites no commits/links (every statement must be backed by the report)')
            rendered = [renderer.block('ref_link', url=html.escape(url), label=html.escape(label)) if url
                        else html.escape(label) for label, url in links]
            refs = renderer.block('refs', links=renderer.block('ref_separator').join(rendered)) if rendered else ''
            # Place the closing period after the citations: "Did X (abc1234)."
            text = text.rstrip()
            end = '.' if text.endswith('.') and not text.endswith('..') and links else ''
            items_html.append(renderer.block('item', text=inline(text[:-1] if end else text), refs=refs, end=end))
        description = section.get('description')
        if description is not None and (not isinstance(description, str) or not description.strip()):
            errors.append(f'{where}.description must be a non-empty string when present')
            description = None
        sections_html.append(renderer.block(
            'section',
            name=html.escape(name),
            description=renderer.block('section_description', text=inline(description)) if description else '',
            items='\n'.join(items_html),
        ))

    summary = text_list(synthesis.get('summary'), 'summary', errors)
    if not summary:
        errors.append('"summary" is required')
    notes = text_list(synthesis.get('notes'), 'notes', errors)

    # Period: explicit, else metadata "since" .. run date
    period = synthesis.get('period')
    if not period and not args.no_report:
        since = str(load_metadata(args.run_dir).get('since') or '')[:10]
        until = run_date(args.run_dir)
        period = f'{since} – {until}' if since and until else since or None

    # Statistics are computed here, never by the model
    stat_rows = []
    if synthesis.get('include_stats', True) and not args.no_report:
        commits = [c for r in repos for c in r['commits']]
        stat_rows.append((labels['repositories'], str(len(repos))))
        stat_rows.append((labels['commits'], str(len(commits))))
        with_stats = [c['stats'] for c in commits if c.get('stats')]
        if with_stats:
            stat_rows.append((labels['lines'], f"+{sum(s.get('additions', 0) for s in with_stats)} / "
                                               f"-{sum(s.get('deletions', 0) for s in with_stats)}"))
        if any(c.get('files') for c in commits):
            stat_rows.append((labels['files'], str(len({f['filename'] for c in commits for f in c.get('files') or []}))))
    for extra in as_list(synthesis.get('extra_stats'), '"extra_stats"', errors):
        if isinstance(extra, dict) and str(extra.get('label', '')).strip() and str(extra.get('value', '')).strip():
            stat_rows.append((str(extra['label']), str(extra['value'])))
        else:
            errors.append('each "extra_stats" entry needs a "label" and a "value"')

    if errors:
        print('Validation failed:', file=sys.stderr)
        for error in errors:
            print(f'  - {error}', file=sys.stderr)
        sys.exit(1)

    if not args.no_report:
        uncited = [(r['name'], c) for r in repos for c in r['commits'] if c['sha'] and (r['name'], c['sha']) not in cited]
        uncited.sort(key=lambda e: (e[1].get('stats') or {}).get('total', 0), reverse=True)
        if uncited:
            shown = uncited if args.all_uncited else uncited[:40]
            warnings.append(f'{len(uncited)} of {total_citable} commits are not cited by any item (largest first):')
            warnings.extend(f"    {c['short']} {name}: {c['subject']}" for name, c in shown)
            if len(uncited) > len(shown):
                warnings.append(f'    ... and {len(uncited) - len(shown)} more (--all-uncited lists all)')
        repeated = sorted(k for k, n in citation_counts.items() if n > 1)
        if repeated:
            warnings.append(f'{len(repeated)} commits are cited in more than one item; check each fits all of them: '
                            + ', '.join(index[sha][0][1]['short'] for _, sha in repeated[:20]))

    stats_html = renderer.block('stats', heading=html.escape(labels['statistics']), rows='\n'.join(
        renderer.block('stat', label=html.escape(label), value=html.escape(value)) for label, value in stat_rows
    )) if stat_rows else ''
    try:
        document = page.substitute(
            lang=html.escape(str(synthesis.get('lang') or 'en')),
            title=html.escape(title),
            period=renderer.block('period', label=html.escape(labels['period']), value=html.escape(period)) if period else '',
            summary='\n'.join(renderer.block('summary_paragraph', text=inline(p)) for p in summary),
            sections='\n'.join(sections_html),
            stats=stats_html,
            notes='\n'.join(renderer.block('note', text=inline(n)) for n in notes),
        )
    except (KeyError, ValueError) as e:
        fail(f'report.html has an unknown placeholder: {e}')
    # Drop blank lines left by empty optional parts
    document = re.sub(r'\n\s*\n', '\n', document)

    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(document)
    print(f'Rendered: {os.path.abspath(out_path)}')
    items_count = sum(len(s.get('items', [])) for s in sections if isinstance(s, dict))
    coverage = 'n/a (--no-report)' if args.no_report else f'{len(cited)}/{total_citable}'
    print(f'Sections: {len(sections_html)}  items: {items_count}  cited commits: {coverage}')
    for warning in warnings:
        print(f'WARNING: {warning}' if not warning.startswith('    ') else warning)


if __name__ == '__main__':
    main()
