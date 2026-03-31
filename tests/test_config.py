"""Tests for config loading and source filtering."""

import pytest
import yaml

from scanner import load_config, get_enabled_sources


class TestLoadConfig:
    """Tests for load_config()."""

    def test_load_valid_config(self, sample_config_file):
        """Should load a valid YAML config file."""
        config = load_config(sample_config_file)
        assert config["scoring"]["threshold"] == 7
        assert len(config["sources"]) == 2

    def test_load_config_file_not_found(self, tmp_path):
        """Should raise FileNotFoundError for missing config."""
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.yaml"))

    def test_load_config_from_env(self, sample_config_file, monkeypatch):
        """Should load config from CONFIG_PATH env var."""
        monkeypatch.setenv("CONFIG_PATH", sample_config_file)
        config = load_config()
        assert config["scoring"]["threshold"] == 7

    def test_config_has_required_sections(self, sample_config_file):
        """Config should have scoring, sources, fetch, storage sections."""
        config = load_config(sample_config_file)
        assert "scoring" in config
        assert "sources" in config
        assert "fetch" in config
        assert "storage" in config

    def test_config_scoring_defaults(self, tmp_path):
        """Config with minimal scoring should still load."""
        minimal = {"scoring": {"threshold": 5}, "sources": []}
        config_path = tmp_path / "minimal.yaml"
        config_path.write_text(yaml.dump(minimal))
        config = load_config(str(config_path))
        assert config["scoring"]["threshold"] == 5


class TestGetEnabledSources:
    """Tests for get_enabled_sources()."""

    def test_filters_disabled_sources(self, sample_config):
        """Should return only enabled sources."""
        sources = get_enabled_sources(sample_config)
        assert len(sources) == 1
        assert sources[0]["name"] == "Test Source"

    def test_empty_sources(self):
        """Should return empty list when no sources."""
        config = {"sources": []}
        assert get_enabled_sources(config) == []

    def test_missing_enabled_field_defaults_true(self):
        """Sources without 'enabled' field should default to enabled."""
        config = {
            "sources": [
                {"name": "No Enabled Field", "url": "https://example.com/feed"},
            ]
        }
        sources = get_enabled_sources(config)
        assert len(sources) == 1

    def test_all_disabled(self):
        """Should return empty list when all sources are disabled."""
        config = {
            "sources": [
                {"name": "A", "enabled": False},
                {"name": "B", "enabled": False},
            ]
        }
        assert get_enabled_sources(config) == []
