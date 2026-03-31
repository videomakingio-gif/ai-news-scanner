# Contributing to AI News Scanner

Thank you for your interest in contributing! 🎉

## How to Contribute

### Reporting Bugs

- Use the [bug report template](https://github.com/videomakingio-gif/ai-news-scanner/issues/new?template=bug_report.md)
- Include your Python version, OS, and the error traceback
- If possible, share your `config.yaml` (remove API keys!)

### Suggesting Features

- Use the [feature request template](https://github.com/videomakingio-gif/ai-news-scanner/issues/new?template=feature_request.md)
- Explain the use case, not just the solution

### Pull Requests

1. Fork the repo and create a branch from `main`
2. If you've added code, add tests (see `tests/`)
3. Ensure all tests pass: `pytest tests/ -v`
4. Run the linter: `flake8 scanner.py tests/`
5. Update documentation if needed
6. Submit a PR using the pull request template

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/ai-news-scanner.git
cd ai-news-scanner

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or: .venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run tests
pytest tests/ -v
```

## Code Standards

- **Type hints**: use them for all function signatures
- **Docstrings**: required for public functions
- **Formatting**: follow PEP 8 (enforced by flake8)
- **Naming**: `snake_case` for functions/variables, `UPPER_CASE` for constants

## Adding a New RSS Source

Just add it to `config.yaml` — no code changes needed:

```yaml
sources:
  - name: "My Source"
    url: "https://example.com/feed.xml"
    lang: "en"  # or "it"
    category: "custom"
    enabled: true
```

## Adding a New LLM Provider

1. Add the provider logic in `scanner.py` inside `_create_llm_scorer()`
2. Add a config example in `examples/`
3. Document it in `README.md`
4. Add tests in `tests/test_scoring.py`

## Adding a New Notification Channel

1. Add the send function in `scanner.py` inside `send_notifications()`
2. Add the config section in `config.yaml`
3. Document it in `README.md`

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
