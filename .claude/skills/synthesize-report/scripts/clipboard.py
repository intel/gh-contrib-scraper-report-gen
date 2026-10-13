# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Copy the rendered report to the system clipboard as rich text (HTML), if the platform allows it.

Usage:
  python clipboard.py check                 # prints JSON: {"available", "method", "reason", ...}
  python clipboard.py copy synthesis.html   # copies the report fragment as HTML (+ plain text where supported)

Methods: Windows PowerShell / pwsh (.NET clipboard, no installs needed), WSL via powershell.exe,
Linux Wayland via wl-copy (wl-clipboard), Linux X11 via xclip. macOS is not supported.
Only the part between <!-- report:start --> and <!-- report:end --> is copied.
"""

import base64
from html.parser import HTMLParser
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__

from _common import configure_stdout, fail  # noqa: E402


def is_wsl() -> bool:
    if os.environ.get('WSL_DISTRO_NAME'):
        return True
    try:
        with open('/proc/version', encoding='utf-8') as f:
            return 'microsoft' in f.read().lower()
    except OSError:
        return False


def detect() -> dict:
    system = platform.system()
    info: dict = {'available': False, 'method': None, 'platform': system, 'reason': '', 'missing': []}
    if system == 'Windows':
        shell = shutil.which('powershell.exe') or shutil.which('pwsh.exe') or shutil.which('pwsh')
        if shell:
            info.update(available=True, method='powershell', command=shell)
        else:
            info.update(reason='Neither Windows PowerShell nor PowerShell 7 was found on PATH',
                        missing=['powershell.exe (built into Windows) or pwsh'])
        return info
    if system == 'Linux':
        if is_wsl():
            shell = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
            if shell and shutil.which('wslpath'):
                info.update(available=True, method='wsl-powershell', command=shell)
                return info
            info['missing'].append('Windows interop (powershell.exe and wslpath on PATH)')
        wayland = bool(os.environ.get('WAYLAND_DISPLAY'))
        x11 = bool(os.environ.get('DISPLAY'))
        if wayland and shutil.which('wl-copy'):
            info.update(available=True, method='wl-copy', command=shutil.which('wl-copy'))
        elif x11 and shutil.which('xclip'):
            info.update(available=True, method='xclip', command=shutil.which('xclip'))
        elif wayland:
            info.update(reason='Wayland session without wl-copy', missing=info['missing'] + ['wl-clipboard (wl-copy)'])
        elif x11:
            info.update(reason='X11 session without xclip', missing=info['missing'] + ['xclip'])
        else:
            remote = ' over SSH' if os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY') else ''
            info.update(reason=f'No graphical session{remote} (neither WAYLAND_DISPLAY nor DISPLAY is set); '
                               'there is no system clipboard to write to from here')
        return info
    info['reason'] = f'Rich-text clipboard copy is not implemented for {system}'
    return info


def extract_fragment(document: str) -> str:
    match = re.search(r'<!-- report:start -->(.*?)<!-- report:end -->', document, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r'<body[^>]*>(.*?)</body>', document, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else document).strip()


class TextExtractor(HTMLParser):
    """Minimal HTML to plain text conversion for the plain-text clipboard alternative."""

    BLOCKS = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'pre', 'div'}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('ul', 'ol'):
            self.depth += 1
        if tag == 'li':
            self.parts.append('\n' + '  ' * (self.depth - 1) + '- ')
        elif tag in self.BLOCKS or tag == 'br':
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('ul', 'ol'):
            self.depth -= 1
        if tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_data(self, data):
        self.parts.append(re.sub(r'\s+', ' ', data))

    def text(self) -> str:
        lines = [line.rstrip() for line in ''.join(self.parts).splitlines()]
        return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip() + '\n'


def to_text(fragment: str) -> str:
    parser = TextExtractor()
    parser.feed(fragment)
    return parser.text()


def cf_html(fragment: str) -> str:
    """Build the Windows CF_HTML payload. Non-ASCII is entity-encoded so byte and character offsets match."""
    fragment = fragment.encode('ascii', 'xmlcharrefreplace').decode('ascii')
    header = 'Version:0.9\r\nStartHTML:{0:010d}\r\nEndHTML:{1:010d}\r\nStartFragment:{2:010d}\r\nEndFragment:{3:010d}\r\n'
    prefix = '<html><head><meta charset="utf-8"></head><body>\r\n<!--StartFragment-->'
    suffix = '<!--EndFragment-->\r\n</body></html>'
    header_len = len(header.format(0, 0, 0, 0))
    start_html = header_len
    start_fragment = start_html + len(prefix)
    end_fragment = start_fragment + len(fragment)
    end_html = end_fragment + len(suffix)
    return header.format(start_html, end_html, start_fragment, end_fragment) + prefix + fragment + suffix


POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$html = [System.IO.File]::ReadAllText($env:SYNTH_CLIP_HTML, [System.Text.Encoding]::UTF8)
$text = [System.IO.File]::ReadAllText($env:SYNTH_CLIP_TEXT, [System.Text.Encoding]::UTF8)
$data = New-Object System.Windows.Forms.DataObject
$data.SetData([System.Windows.Forms.DataFormats]::Html, $html)
$data.SetData([System.Windows.Forms.DataFormats]::UnicodeText, $text)
[System.Windows.Forms.Clipboard]::SetDataObject($data, $true)
"""


def copy_powershell(command: str, fragment: str, wsl: bool) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        html_path, text_path = os.path.join(tmp, 'clip.html'), os.path.join(tmp, 'clip.txt')
        with open(html_path, 'w', encoding='utf-8', newline='') as f:
            f.write(cf_html(fragment))
        with open(text_path, 'w', encoding='utf-8', newline='') as f:
            f.write(to_text(fragment).replace('\n', '\r\n'))
        env = dict(os.environ)
        try:
            if wsl:
                html_path, text_path = (subprocess.run(['wslpath', '-w', p], capture_output=True, text=True, check=True)
                                        .stdout.strip() for p in (html_path, text_path))
                # Forward the variables to the Windows process
                env['WSLENV'] = ':'.join(filter(None, [env.get('WSLENV'), 'SYNTH_CLIP_HTML', 'SYNTH_CLIP_TEXT']))
            env['SYNTH_CLIP_HTML'], env['SYNTH_CLIP_TEXT'] = html_path, text_path
            encoded = base64.b64encode(POWERSHELL_SCRIPT.encode('utf-16-le')).decode('ascii')
            result = subprocess.run(
                [command, '-NoProfile', '-NonInteractive', '-STA', '-OutputFormat', 'Text', '-EncodedCommand', encoded],
                stdin=subprocess.DEVNULL, capture_output=True, encoding='utf-8', errors='replace', timeout=60, env=env)
        except (OSError, subprocess.SubprocessError) as e:
            fail(f'PowerShell clipboard copy failed: {e}')
        if result.returncode != 0:
            fail(f'PowerShell clipboard copy failed: {(result.stderr or result.stdout).strip()}')


def copy_unix(method: str, command: str, fragment: str) -> None:
    args = [command, '--type', 'text/html'] if method == 'wl-copy' else [command, '-selection', 'clipboard', '-t', 'text/html']
    with tempfile.TemporaryFile() as f:
        f.write(fragment.encode('utf-8'))
        f.seek(0)
        # The tools fork to keep serving the clipboard; don't capture output or we would wait for the fork
        try:
            result = subprocess.run(args, stdin=f, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            fail(f'{method} failed: {e}')
    if result.returncode != 0:
        fail(f'{method} exited with code {result.returncode}')


def main() -> None:
    configure_stdout()
    if len(sys.argv) < 2 or sys.argv[1] not in ('check', 'copy') or (sys.argv[1] == 'copy' and len(sys.argv) != 3):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    info = detect()
    if sys.argv[1] == 'check':
        print(json.dumps(info, indent=2))
        return
    if not info['available']:
        fail(f"Clipboard copy unavailable: {info['reason']}")
    with open(sys.argv[2], encoding='utf-8') as f:
        fragment = extract_fragment(f.read())
    if info['method'] in ('powershell', 'wsl-powershell'):
        copy_powershell(info['command'], fragment, wsl=info['method'] == 'wsl-powershell')
    else:
        copy_unix(info['method'], info['command'], fragment)
    print(f"Copied report to clipboard as rich text via {info['method']}")


if __name__ == '__main__':
    main()
