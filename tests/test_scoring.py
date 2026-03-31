"""Tests for LLM scoring logic."""

from unittest.mock import MagicMock
from types import SimpleNamespace

from scanner import score_article, SCORING_TEMPLATE


def _mock_anthropic_response(text):
    """Create a mock Anthropic API response."""
    response = MagicMock()
    response.content = [SimpleNamespace(text=text)]
    return response


class TestScoreArticle:
    """Tests for score_article()."""

    def _config(self, provider="anthropic"):
        return {
            "scoring": {
                "provider": provider,
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "profile": "Test scoring profile.",
            }
        }

    def test_parses_valid_json_response(self, sample_article):
        """Should correctly parse a clean JSON response."""
        client = MagicMock()
        client.messages.create.return_value = _mock_anthropic_response(
            '{"score": 8, "reason": "Relevant AI news", "tags": ["ai", "claude"]}'
        )
        result = score_article(client, sample_article, self._config())

        assert result is not None
        assert result["relevance_score"] == 8
        assert result["relevance_reason"] == "Relevant AI news"
        assert "ai" in result["tags"]
        assert "hash" in result
        assert "scored_at" in result

    def test_parses_markdown_wrapped_json(self, sample_article):
        """Should handle JSON wrapped in markdown code blocks."""
        client = MagicMock()
        client.messages.create.return_value = _mock_anthropic_response(
            '```json\n{"score": 7, "reason": "Good article", "tags": ["tech"]}\n```'
        )
        result = score_article(client, sample_article, self._config())

        assert result is not None
        assert result["relevance_score"] == 7

    def test_parses_json_with_surrounding_text(self, sample_article):
        """Should extract JSON from response with surrounding text."""
        client = MagicMock()
        client.messages.create.return_value = _mock_anthropic_response(
            'Here is my assessment: {"score": 6, "reason": "Moderate", "tags": ["ai"]}'
        )
        result = score_article(client, sample_article, self._config())

        assert result is not None
        assert result["relevance_score"] == 6

    def test_returns_none_for_unparseable(self, sample_article):
        """Should return None when response can't be parsed as JSON."""
        client = MagicMock()
        client.messages.create.return_value = _mock_anthropic_response(
            "I cannot score this article."
        )
        result = score_article(client, sample_article, self._config())

        assert result is None

    def test_returns_none_on_api_error(self, sample_article):
        """Should return None when API call fails."""
        client = MagicMock()
        client.messages.create.side_effect = Exception("API Error")

        result = score_article(client, sample_article, self._config())
        assert result is None

    def test_hash_is_deterministic(self, sample_article):
        """Same article should always produce the same hash."""
        client = MagicMock()
        client.messages.create.return_value = _mock_anthropic_response(
            '{"score": 5, "reason": "OK", "tags": []}'
        )
        r1 = score_article(client, sample_article.copy(), self._config())
        r2 = score_article(client, sample_article.copy(), self._config())

        assert r1["hash"] == r2["hash"]

    def test_defaults_for_missing_fields(self, sample_article):
        """Should use defaults when JSON response has missing fields."""
        client = MagicMock()
        client.messages.create.return_value = _mock_anthropic_response(
            '{"score": 3}'
        )
        result = score_article(client, sample_article, self._config())

        assert result is not None
        assert result["relevance_score"] == 3
        assert result["relevance_reason"] == ""
        assert result["tags"] == []


class TestScoringTemplate:
    """Tests for the scoring template."""

    def test_template_formats_correctly(self):
        """Template should accept profile, title, source, summary."""
        result = SCORING_TEMPLATE.format(
            profile="Test profile",
            title="Test Title",
            source="Test Source",
            summary="Test summary text",
        )
        assert "Test profile" in result
        assert "Test Title" in result
        assert "Test Source" in result
        assert "Test summary text" in result

    def test_template_contains_json_instruction(self):
        """Template should instruct for JSON output."""
        assert "JSON" in SCORING_TEMPLATE
        assert "score" in SCORING_TEMPLATE
        assert "reason" in SCORING_TEMPLATE
        assert "tags" in SCORING_TEMPLATE
