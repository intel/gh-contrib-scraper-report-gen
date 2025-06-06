# GHContribScraperReportGen

A tool to download all commits made by a GitHub user across specified repositories within a date range using GitHub API. Additionally, it can fetch commits made in pull requests by the user instead of just the final PR merge commit.

The tool generates diffs for each commit and provides text reports of all commits grouped by repositories.

Known limitations:

- The tool does not automatically scrape all repositories a user has contributed to. You need to specify the repositories you want to scan.

- Only commits made to the default branch of the specified repositories are fetched.

- End date is not supported. The tool will fetch all commits made after the specified start date until the current date.

Prerequisites:

- Python 3.10 or higher

## Quick Installation

1. Clone this repository, download the ZIP or a release.

2. Run `.\run.ps1`.

`\.run.ps1` is a PowerShell script that automates the installation of dependencies and the execution of the tool with the GUI. It also creates a virtual environment if it doesn't exist.

## Manual installation

1. Clone this repository or download the ZIP.

2. Create a virtual environment:

   ```powershell
   python -m venv .venv ; .\.venv\Scripts\Activate.ps1
   ```

   > __NOTE__: This step is optional but recommended to avoid dependency conflicts with other projects. It will be created automatically if you use the run script though.

3. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

   Or use the run script:

   ```powershell
   .\run.ps1 -Tasks install
   ```

   > __NOTE__: If using the run script, to provide custom pip flags, set the `PIP_INSTALL_FLAGS` environment variable before running. For example:
   >
   > ```powershell
   > $env:PIP_INSTALL_FLAGS="--upgrade --trusted-host my.host"
   > .\run.ps1 -Tasks install
   > ```
   >
   > You don't actually need to run the `install` task if you are using the run script, as it will automatically install dependencies if they are not already installed when you run it with no additional params.

## Setting up GitHub Personal Access Token

   - Create tokens at [GitHub Personal Access Tokens page](https://github.com/settings/tokens) for all owners/organizations you want to scan.

   - For better security, consider using fine-grained tokens with the minimum required permissions (Read-only: Contents, Pull requests).
   Make sure to select the desired organization as the resource owner.

   - Set it as an environment variable:

      ```powershell
      $env:GITHUB_TOKEN="your_token_here"
      ```

   - Or create a `.env` file with your token:

      ```plain
      GITHUB_TOKEN=your_token_here
      ```

      > __NOTE__: The `.env` variables are loaded automatically only when using the run script.

   - Or pass it as a command-line `--token` argument or in the GUI.

   > __NOTE__: If you are using multiple tokens, instead of passing a single token to the environment variable or command line parameter, you can pass a map of owner tokens (comma-separated `owner:token` pairs, e.g., `owner1:token1,owner2:token2`). The scraper will use the appropriate token for each repository based on its owner.

## Usage

### Graphical User Interface (GUI)

A web‑based interface is available via NICEGUI. It exposes all CLI options (username, repositories, date, tokens, commit fields, report formats, etc.) with field validation and streams logs live. After completion, navigate to the output directory to view results.

```powershell
python -m src.main_gui
```

or

```powershell
.\run.ps1 -Tasks gui
```

This will launch the GUI in your browser at __<http://localhost:8080/>__ and guide you through the inputs.

> __NOTE__: If run via the run script, the GUI will automatically load the `.env` file and set the environment variables. Providing the repositories and/or token(s) via the GUI will override the environment variables.

### Command Line Interface (CLI)

```powershell
python -m src.main <username> --since "YYYY-MM-DD" `
   [--token "your_token_or_map_of_tokens"] `
   [--repositories "owner1/repo1,owner2/repo2"] `
   [--output OUTPUT] [--ca-bundle CA_BUNDLE_PATH] [--no-verify-ssl] [--fetch-pr-commits] [--include-merge-commits] `
   [--commit-fields date url message sha stats files_changed] `
   [--report-formats markdown text json] `
   [--limit-download-diffs LIMIT_OF_FILES LIMIT_LINES_CHANGED]
```

- __username__: The GitHub username to scan

- __--since__: Only include contributions after this date (required)

- __--token__: GitHub Personal Access Token or a map of owner tokens (can also be set via environment variable)

- __--repositories__: Comma-separated list of repositories (can also be set via environment variable)

- __--output__: Output directory for the results (default: `output/`)

- __--ca-bundle__: Path to a custom SSL CA bundle file

- __--no-verify-ssl__: Disable SSL verification (not recommended)

- __--fetch-pr-commits__: Fetch any commits made in pull requests

- __--include-merge-commits__: Include merge commits

- __--commit-fields__: Space-separated list of commit fields to include in reports.
  Possible values: `date`, `url`, `message`, `sha`, `stats`, `files_changed`.
  Default fields: `date`, `url`, `message`.

- __--report-formats__: Space-separated list of report formats to generate. Options: `text`, `markdown`, `json`. Default: `text`

- __--limit-download-diffs__: Limit downloading diffs for commits whose file count or total lines changed exceed the given thresholds. Provide two integers: `LIMIT_OF_FILES` and `LIMIT_LINES_CHANGED`. Defaults are `30` and `3000`. Commits above either limit are skipped with an informational log.

#### Date Format

The `--since` parameter accepts the following date formats:

- `YYYY-MM-DD` (e.g., "2023-01-01")

- `YYYY-MM-DD HH:MM:SS` (e.g., "2023-01-01 00:00:00")

#### Example

```powershell
python -m src.main octocat --repositories "octocat/Hello-World" --since "2022-01-01" --fetch-pr-commits --token "your_token_here"
```

This will fetch direct commits, pull request commits made by __octocat__ since the given date, store diffs in an output directory, and generate a report listing all direct commits and commits made in __octocat__ PRs.

#### Setting Repositories via Environment Variable

You can also set the repositories to scan using an environment variable:

```powershell
$env:GITHUB_REPOSITORIES="owner/repo1,owner/repo2"
python -m src.main <username> --since "2023-01-01" --token "your_token_here"
```

Or in your `.env` file:

```plain
GITHUB_REPOSITORIES=owner/repo1,owner/repo2
```

> __BTW__: Unfortunately, a working solution to enable automatic scraping all repositories user contributed to has not been found. It would seem GitHub API doesn't provide a straightforward way to retrieve all repositories a user has contributed to, especially if they are private or part of an organization. The best approach seems to be to manually specify the repositories user might want to scan.

#### Using the Run Script

The included PowerShell run script provides a convenient way to run the application:

```powershell
.\run.ps1 -Task cli -PythonArgs "<username> --repositories owner/repo1,owner/repo2 --since 2023-01-01 --fetch-pr-commits"
```

It will also automatically create a virtual environment if it doesn't exist and install the required dependencies.

#### VSCode Tasks

The repository includes VSCode tasks for common operations:

- __Run CLI__: Runs the application with the prompted arguments

- __Run GUI__: Opens the GUI interface

## Output Format

### Metadata JSON

The `metadata.json` file contains metadata about the query, including:

- Username

- List of repositories

- Start date (`since`)

### Commit Diffs

The `commits/` directory will contain `.diff` files for each commit (both direct and, if included, from PRs) named by their SHA. Each `.diff` file includes:

- File names and paths modified in the commit

- Status of each file (added, modified, removed)

- Changes summary (+additions/-deletions)

- Patch/diff contents showing the actual code changes

### Reports

The tool can generate any combination of the following report files based on the `--report-formats` setting:

- __report.txt__: Plain‑text report (when `text` is selected)

- __report.md__: Markdown report (when `markdown` is selected)

- __report.json__: JSON report (when `json` is selected)

## Network Configuration

### Proxy Settings

If you're behind a corporate proxy, you may need to configure proxy settings:

1. Add to your `.env` file:

   ```plain
   HTTP_PROXY=http://your-proxy-server:port
   HTTPS_PROXY=http://your-proxy-server:port
   ```

2. This helps resolve `ConnectTimeoutError` issues when connecting to GitHub.

### SSL Certificate Issues

If you encounter SSL verification errors:

- 1st option: Point pip to use system certificates by setting `SSL_CERT_FILE` environment variable:

   ```powershell
   $env:SSL_CERT_FILE="C:\path\to\your\CAcert.crt"
   ```

- 2nd option: Use the `--ca-bundle` parameter to specify a certificate bundle:

   ```powershell
   python -m src.main <username> --repositories "owner/repo" --since "2023-01-01" --ca-bundle "C:\path\to\your\CAcert.crt"
   ```

- 3rd option: If you're still facing issues, consider installing an additional package like `pip-system-certs` to use system certificates:

   ```powershell
   pip install pip-system-certs
   ```

   This will automatically configure pip to use the system's CA certificates.

- 4th option: As a last resort (not secure), use `--no-verify-ssl`.
