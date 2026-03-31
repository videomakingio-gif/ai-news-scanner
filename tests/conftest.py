"""Shared test fixtures for AI News Scanner tests."""

import json
import pytest
from datetime import datetime, timezone


@pytest.fixture
def sample_config():
    """Minimal valid config for testing."""
    return {
        "scoring": {
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "threshold": 7,
            "max_tokens": 100,
            "profile": "Test relevance profile for AI news.",
        },
        "sources": [
            {
                "name": "Test Source",
                "url": "https://example.com/feed.xml",
                "lang": "en",
                "category": "test",
                "enabled": True,
            },
            {
                "name": "Disabled Source",
                "url": "https://example.com/disabled.xml",
                "lang": "en",
                "category": "test",
                "enabled": False,
            },
        ],
        "fetch": {
            "max_articles_per_source": 5,
            "hours_lookback": 26,
            "timeout_seconds": 10,
            "user_agent": "TestAgent/1.0",
        },
        "storage": {
            "backend": "local",
            "local_path": "./test_output",
            "dedup_days": 3,
        },
        "output": {
            "format": "json",
            "write_latest": True,
        },
    }


@pytest.fixture
def sample_article():
    """A sample article dict as returned by fetch_articles."""
    return {
        "title": "Claude 4 Released with Advanced Reasoning",
        "url": "https://example.com/article/1",
        "summary": "Anthropic announced Claude 4 today with major improvements.",
        "source": "Test Source",
        "category": "lab",
        "lang": "en",
        "published": "2026-03-31T08:00:00+00:00",
    }


@pytest.fixture
def scored_article(sample_article):
    """A sample article with scoring fields added."""
    article = sample_article.copy()
    article.update({
        "relevance_score": 9,
        "relevance_reason": "Major Claude release",
        "tags": ["claude", "anthropic", "llm"],
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "hash": "a1b2c3d4e5f6",
    })
    return article


@pytest.fixture
def sample_config_file(tmp_path, sample_config):
    """Write sample config to a temp YAML file and return the path."""
    import yaml
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(sample_config), encoding="utf-8")
    return str(config_path)


@pytest.fixture
def output_dir(tmp_path):
    """Create and return a temporary output directory."""
    out = tmp_path / "output"
    out.mkdir()
    return out


@pytest.fixture
def sample_scan_file(output_dir, scored_article):
    """Write a sample scan JSON file to output dir."""
    scan_file = output_dir / "2026-03-30.json"
    scan_file.write_text(
        json.dumps([scored_article], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return scan_file
