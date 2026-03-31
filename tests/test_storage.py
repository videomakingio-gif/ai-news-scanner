"""Tests for storage backends and deduplication."""

import json
from datetime import datetime, timezone

from scanner import _save_local, save_articles, load_recent_hashes


class TestSaveLocal:
    """Tests for _save_local()."""

    def test_saves_json_file(self, output_dir, scored_article):
        """Should save articles to a dated JSON file."""
        config = {"storage": {"local_path": str(output_dir)}, "output": {"write_latest": False}}
        _save_local([scored_article], "2026-03-31", config)

        out_file = output_dir / "2026-03-31.json"
        assert out_file.exists()

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["title"] == scored_article["title"]

    def test_saves_latest_json(self, output_dir, scored_article):
        """Should create latest.json when write_latest is True."""
        config = {"storage": {"local_path": str(output_dir)}, "output": {"write_latest": True}}
        _save_local([scored_article], "2026-03-31", config)

        latest = output_dir / "latest.json"
        assert latest.exists()

        data = json.loads(latest.read_text(encoding="utf-8"))
        assert data["date"] == "2026-03-31"
        assert data["count"] == 1
        assert len(data["articles"]) == 1

    def test_skips_latest_when_disabled(self, output_dir, scored_article):
        """Should not create latest.json when write_latest is False."""
        config = {"storage": {"local_path": str(output_dir)}, "output": {"write_latest": False}}
        _save_local([scored_article], "2026-03-31", config)

        assert not (output_dir / "latest.json").exists()

    def test_creates_output_dir(self, tmp_path, scored_article):
        """Should create the output directory if it doesn't exist."""
        new_dir = tmp_path / "new_output"
        config = {"storage": {"local_path": str(new_dir)}, "output": {"write_latest": False}}
        _save_local([scored_article], "2026-03-31", config)

        assert new_dir.exists()
        assert (new_dir / "2026-03-31.json").exists()

    def test_handles_empty_articles(self, output_dir):
        """Should save empty array for no articles."""
        config = {"storage": {"local_path": str(output_dir)}, "output": {"write_latest": False}}
        _save_local([], "2026-03-31", config)

        data = json.loads((output_dir / "2026-03-31.json").read_text(encoding="utf-8"))
        assert data == []


class TestSaveArticles:
    """Tests for save_articles() router."""

    def test_routes_to_local(self, output_dir, scored_article):
        """Should route to local backend when configured."""
        config = {
            "storage": {"backend": "local", "local_path": str(output_dir)},
            "output": {"write_latest": False},
        }
        save_articles([scored_article], "2026-03-31", config)
        assert (output_dir / "2026-03-31.json").exists()

    def test_defaults_to_local(self, output_dir, scored_article):
        """Should default to local backend when not specified."""
        config = {
            "storage": {"local_path": str(output_dir)},
            "output": {"write_latest": False},
        }
        save_articles([scored_article], "2026-03-31", config)
        assert (output_dir / "2026-03-31.json").exists()


class TestLoadRecentHashes:
    """Tests for load_recent_hashes()."""

    def test_loads_hashes_from_previous_scans(self, output_dir, scored_article):
        """Should load hashes from existing scan files."""
        # Write a scan file for "yesterday"
        from datetime import timedelta
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        scan_file = output_dir / f"{yesterday}.json"
        scan_file.write_text(
            json.dumps([scored_article], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        config = {
            "storage": {
                "backend": "local",
                "local_path": str(output_dir),
                "dedup_days": 3,
            }
        }
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        hashes = load_recent_hashes(today, config)

        assert scored_article["hash"] in hashes

    def test_returns_empty_when_no_history(self, output_dir):
        """Should return empty set when no previous scans exist."""
        config = {
            "storage": {
                "backend": "local",
                "local_path": str(output_dir),
                "dedup_days": 3,
            }
        }
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        hashes = load_recent_hashes(today, config)

        assert len(hashes) == 0

    def test_dedup_days_respected(self, output_dir, scored_article):
        """Should only look back dedup_days."""
        from datetime import timedelta
        # Write a scan file for 5 days ago
        old_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        scan_file = output_dir / f"{old_date}.json"
        scan_file.write_text(
            json.dumps([scored_article], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        config = {
            "storage": {
                "backend": "local",
                "local_path": str(output_dir),
                "dedup_days": 3,  # Only look back 3 days
            }
        }
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        hashes = load_recent_hashes(today, config)

        # 5-day-old hash should NOT be loaded (dedup_days=3)
        assert scored_article["hash"] not in hashes
