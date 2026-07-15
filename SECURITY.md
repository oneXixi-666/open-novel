# Security Policy

Open Novel is a local-first writing tool. The main security boundary is the local novel project folder.

## Supported Practices

- API keys should live in user config or environment variables, never in novel projects.
- CLI agents should run read-only by default.
- Write access must be restricted to allowed project paths.
- `chapters/` and `memory/` updates should require explicit confirmation.
- Run logs must redact secrets.

## Reporting

For now, open a private maintainer channel or issue with a minimal reproduction. Do not include API keys, private manuscripts, or local credential files.
