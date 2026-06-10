# Contributing

Thanks for helping improve yema.

## Development

Set up the project with `uv`:

```bash
uv sync
uv run yema --help
```

Before opening a pull request, run the relevant command manually against a test
qBittorrent/yemapt setup when possible.

## Pull Requests

- Keep changes focused on one behavior or fix.
- Do not commit real credentials, torrent files, tracker URLs with passkeys, or
  debug files.
- Update `README.md` when command behavior or user-facing configuration changes.
- Add tracker display names in `yema/tracker_map.py` using the existing mapping
  format.
- Prefer small, reproducible examples when reporting bugs.

## Security

For security issues, follow `SECURITY.md` instead of opening a public issue.
