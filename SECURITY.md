# Security Policy

## Reporting Security Issues

Please do not report security issues in public GitHub issues.

Send a private report to the maintainer email listed in `pyproject.toml`, and
include enough detail to reproduce the issue without exposing real account
credentials.

## Sensitive Data

Do not paste the following into issues, pull requests, logs, screenshots, or
debug attachments:

- yemapt `Authorization` values
- qBittorrent usernames or passwords
- tracker URLs containing passkeys, credentials, uid values, or tokens
- torrent files or raw torrent response bodies
- download URLs or generated download tokens
- local save paths that reveal private directory names
- files generated under `tmp/` while debug mode is enabled

If debug output is needed for troubleshooting, redact sensitive values before
sharing it.
