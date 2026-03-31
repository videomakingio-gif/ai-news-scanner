# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2026-03-31

### Added
- **Multi-LLM support**: OpenAI and Google Gemini alongside Anthropic Claude
- **Notifications**: Telegram and Slack integration for scan results
- **Unit tests**: comprehensive test suite with pytest
- **CI/CD**: GitHub Actions for lint, test, and Docker build
- **Community files**: CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md
- **Issue/PR templates** for GitHub
- **Retry logic** with exponential backoff for LLM API calls
- **New Italian sources**: IlSole24Ore Tech, CorCom, HDblog
- **Config examples**: OpenAI and Gemini configurations
- README badges, embedded GIF demo, new documentation sections

### Changed
- `scoring.provider` config field to select LLM provider (default: `anthropic`)
- Improved error handling for LLM response parsing

## [1.0.0] — 2026-03-31

### Added
- Initial release
- RSS/Atom feed scanning from 21 configurable sources
- LLM-powered relevance scoring with Claude Haiku
- Customizable scoring profile via YAML config
- Hash-based deduplication (3-day window)
- Dual storage backend: Google Cloud Storage + local filesystem
- Cloud Run Job deployment with Cloud Scheduler
- CLI with `--config` flag and `CONFIG_PATH` env support
- Italian sources: AI4Business, Agenda Digitale, StartupItalia, Wired Italia, Ninja Marketing, Key4biz
