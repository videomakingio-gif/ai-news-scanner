# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.x     | ✅ Yes             |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Email **giovanni@giovanniliguori.it** with:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
3. You will receive a response within 48 hours

## Security Practices

- API keys are never stored in code — use environment variables or Secret Manager
- The `.env` file is excluded from version control via `.gitignore`
- For production, use Google Cloud Secret Manager (see `deploy.sh`)
- RSS feed content is sanitized (HTML stripped) before processing
- No user input is passed to shell commands
