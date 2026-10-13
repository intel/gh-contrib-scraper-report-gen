<!-- Copyright (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Rich-text clipboard support

`scripts/clipboard.py check` reports `available`, `method`, `reason`, `missing`. Give the user the
matching instructions below only when they ask how to enable it.

| Platform | Method | What is needed |
|---|---|---|
| Windows | `powershell` | Nothing: built-in Windows PowerShell (or PowerShell 7). Copies HTML and plain text. |
| WSL | `wsl-powershell` | Windows interop enabled (default): `powershell.exe` and `wslpath` on PATH. |
| Linux, Wayland | `wl-copy` | wl-clipboard: `sudo apt install wl-clipboard` / `sudo dnf install wl-clipboard` / `sudo pacman -S wl-clipboard` |
| Linux, X11 | `xclip` | xclip: `sudo apt install xclip` / `sudo dnf install xclip` / `sudo pacman -S xclip` |
| macOS | -- | Not supported; open `synthesis.html` in a browser and copy manually. |

Check the session type with `echo $XDG_SESSION_TYPE` (`wayland` or `x11`). After installing, re-run
`clipboard.py check`.
On Linux only the HTML flavour is set; plain-text-only targets may paste nothing.

## Remote sessions (SSH, VS Code Remote, containers)

If `reason` says there is no graphical session, Claude Code is running on a machine whose clipboard
is not the user's. Installing tools there does not help. Options:

1. Run Claude Code on the machine with the browser (e.g. natively on Windows or in WSL there), where
   the copy works out of the box.
2. Get `synthesis.html` to the local machine (VS Code: right-click the file > Download; or `scp`),
   then either open it in a browser and press Ctrl+A, Ctrl+C, or, with Python installed locally, run
   `python clipboard.py copy synthesis.html` using a local copy of this skill's `scripts/` folder.
3. X11 forwarding is not recommended: common Windows X servers sync only plain text to the
   Windows clipboard, so formatting is lost.
