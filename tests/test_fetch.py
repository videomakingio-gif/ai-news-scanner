"""Tests for RSS feed fetching."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from scanner import fetch_articles


class FeedEntry(dict):
    """Mock feedparser entry that supports both dict .get() and attribute access."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def _make_entry(title, link, summary, pub_time=None):
    """Helper to create a mock feedparser entry."""
    entry = FeedEntry(
        title=title,
        link=link,
        summary=summary,
    )
    if pub_time:
        entry["published_parsed"] = pub_time.timetuple()[:6] + (0, 0, 0)
    else:
        entry["published_parsed"] = None
    entry["updated_parsed"] = None
    return entry


class TestFetchArticles:
    """Tests for fetch_articles()."""

    def _source(self, name="Test", url="https://example.com/feed"):
        return {"name": name, "url": url, "lang": "en", "category": "test"}

    def _config(self, max_articles=5, hours_lookback=26):
        return {
            "fetch": {
                "max_articles_per_source": max_articles,
                "hours_lookback": hours_lookback,
                "timeout_seconds": 10,
                "user_agent": "Test/1.0",
            }
        }

    @patch("scanner.feedparser.parse")
    def test_fetch_returns_articles(self, mock_parse):
        """Should return articles from parsed feed."""
        now = datetime.now(timezone.utc)
        mock_parse.return_value = MagicMock(
            entries=[
                _make_entry("Article 1", "https://example.com/1", "Summary 1", now),
                _make_entry("Article 2", "https://example.com/2", "Summary 2", now),
            ]
        )
        cutoff = now - timedelta(hours=26)
        articles = fetch_articles(self._source(), cutoff, self._config())

        assert len(articles) == 2
        assert articles[0]["title"] == "Article 1"
        assert articles[0]["source"] == "Test"
        assert articles[0]["lang"] == "en"

    @patch("scanner.feedparser.parse")
    def test_filters_old_articles(self, mock_parse):
        """Should filter out articles older than cutoff."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=48)
        mock_parse.return_value = MagicMock(
            entries=[
                _make_entry("New", "https://example.com/1", "New article", now),
                _make_entry("Old", "https://example.com/2", "Old article", old),
            ]
        )
        cutoff = now - timedelta(hours=26)
        articles = fetch_articles(self._source(), cutoff, self._config())

        assert len(articles) == 1
        assert articles[0]["title"] == "New"

    @patch("scanner.feedparser.parse")
    def test_strips_html_from_summary(self, mock_parse):
        """Should strip HTML tags from article summaries."""
        now = datetime.now(timezone.utc)
        mock_parse.return_value = MagicMock(
            entries=[
                _make_entry("Test", "https://example.com/1",
                            "<p>This is <b>bold</b> text</p>", now),
            ]
        )
        cutoff = now - timedelta(hours=26)
        articles = fetch_articles(self._source(), cutoff, self._config())

        assert "<" not in articles[0]["summary"]
        assert "This is bold text" in articles[0]["summary"]

    @patch("scanner.feedparser.parse")
    def test_respects_max_articles(self, mock_parse):
        """Should limit articles per source to max_articles_per_source."""
        now = datetime.now(timezone.utc)
        entries = [
            _make_entry(f"Art {i}", f"https://example.com/{i}", f"Sum {i}", now)
            for i in range(10)
        ]
        mock_parse.return_value = MagicMock(entries=entries)

        cutoff = now - timedelta(hours=26)
        articles = fetch_articles(self._source(), cutoff, self._config(max_articles=3))

        assert len(articles) == 3

    @patch("scanner.feedparser.parse")
    def test_handles_fetch_error(self, mock_parse):
        """Should return empty list on fetch error."""
        mock_parse.side_effect = Exception("Network error")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=26)
        articles = fetch_articles(self._source(), cutoff, self._config())

        assert articles == []

    @patch("scanner.feedparser.parse")
    def test_handles_missing_date(self, mock_parse):
        """Articles without published date should still be included."""
        mock_parse.return_value = MagicMock(
            entries=[_make_entry("No Date", "https://example.com/1", "Summary", None)]
        )
        cutoff = datetime.now(timezone.utc) - timedelta(hours=26)
        articles = fetch_articles(self._source(), cutoff, self._config())

        assert len(articles) == 1
        assert articles[0]["published"] is None

    @patch("scanner.feedparser.parse")
    def test_truncates_long_summary(self, mock_parse):
        """Should truncate summaries longer than 500 chars."""
        now = datetime.now(timezone.utc)
        long_summary = "A" * 600
        mock_parse.return_value = MagicMock(
            entries=[_make_entry("Test", "https://example.com/1", long_summary, now)]
        )
        cutoff = now - timedelta(hours=26)
        articles = fetch_articles(self._source(), cutoff, self._config())

        assert len(articles[0]["summary"]) <= 500
