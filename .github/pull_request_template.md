## Summary

<!-- What does this change do, and why? Link related issues (e.g. "Fixes #123"). -->

## Security checklist

<!-- Tick what applies; explain any item you leave unticked or mark as not applicable. -->

- [ ] No secrets, tokens or personal data in code, logs, test data or screenshots
- [ ] Tokens and other sensitive values are never logged, printed or written to reports
- [ ] External input (CLI arguments, `.env` values, API responses, files) is validated before use
- [ ] Subprocesses use argument lists, never `shell=True`; no `eval`/`exec` on external data
- [ ] TLS certificate verification stays enabled by default
- [ ] New or updated dependencies are needed, maintained and free of known vulnerabilities; `.bom` is updated if the resolved set changed
- [ ] New or changed workflows pin actions to a full commit SHA and request least-privilege `permissions`
- [ ] CodeQL, Bandit and dependency review pass, or each finding is fixed or explained below

## Testing

<!-- How did you test this change? -->

## Notes for the reviewer

<!-- Anything a reviewer should look at closely: risky areas, trade-offs, findings explained above. -->
