"""
AI News Scanner — Intelligent RSS aggregator with LLM-powered relevance scoring.

Scans configurable RSS/Atom sources, scores each article against your
professional profile using Claude Haiku, and saves only what matters.

Deploy as a Cloud Run Job with Cloud Scheduler for daily automation.
Cost: ~€0.003/execution (~150 articles scored with Haiku).

GitHub: github.com/videomakingio/ai-news-scanner
License: MIT
"""

import os
import re
import json
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml
import feedparser
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ai-news-scanner")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: str = None) -> dict:
    """Load configuration from YAML file.

    Priority:
    1. Path passed as argument
    2. CONFIG_PATH environment variable
    3. config.yaml in the same directory as this script
    """
    if path is None:
        path = os.environ.get("CONFIG_PATH", None)
    if path is None:
        path = Path(__file__).parent / "config.yaml"

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy config.yaml from the repo and customize it."
        )

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    log.info(f"Config loaded from {path}")
    return config


def get_enabled_sources(config: dict) -> list[dict]:
    """Return only enabled sources from config."""
    return [s for s in config.get("sources", []) if s.get("enabled", True)]


# ---------------------------------------------------------------------------
# RSS Fetch
# ---------------------------------------------------------------------------

def fetch_articles(source: dict, cutoff: datetime, config: dict) -> list[dict]:
    """Fetch recent articles from an RSS/Atom feed."""
    fetch_cfg = config.get("fetch", {})
    timeout = fetch_cfg.get("timeout_seconds", 10)
    max_articles = fetch_cfg.get("max_articles_per_source", 5)
    user_agent = fetch_cfg.get("user_agent", "AINewsScanner/1.0")

    try:
        feed = feedparser.parse(
            source["url"],
            agent=user_agent,
            # feedparser doesn't support timeout natively;
            # we rely on socket default timeout
        )
        articles = []

        for entry in feed.entries[:max_articles]:
            # Parse publication date
            published = None
            for date_field in ("published_parsed", "updated_parsed"):
                if hasattr(entry, date_field) and getattr(entry, date_field):
                    published = datetime(
                        *getattr(entry, date_field)[:6], tzinfo=timezone.utc
                    )
                    break

            if published and published < cutoff:
                continue

            # Extract summary, strip HTML
            summary = ""
            if hasattr(entry, "summary"):
                summary = entry.summary[:500]
            elif hasattr(entry, "description"):
                summary = entry.description[:500]
            summary = re.sub(r"<[^>]+>", "", summary).strip()

            articles.append({
                "title": entry.get("title", "N/A"),
                "url": entry.get("link", ""),
                "summary": summary,
                "source": source["name"],
                "category": source.get("category", ""),
                "lang": source.get("lang", "en"),
                "published": published.isoformat() if published else None,
            })

        log.info(f"  {source['name']}: {len(articles)} recent articles")
        return articles

    except Exception as e:
        log.warning(f"  {source['name']}: fetch error — {e}")
        return []


# ---------------------------------------------------------------------------
# LLM Scoring
# ---------------------------------------------------------------------------

SCORING_TEMPLATE = """Valuta questo articolo da 1 a 10 in base a quanto e' rilevante per il profilo descritto sotto.

--- PROFILO ---
{profile}

--- ISTRUZIONI ---
Rispondi SOLO con un JSON valido (niente markdown, niente commenti):
{{"score": N, "reason": "motivo in 10 parole max", "tags": ["tag1", "tag2"]}}

--- ARTICOLO ---
Titolo: {title}
Fonte: {source}
Sommario: {summary}"""


def score_article(
    client: anthropic.Anthropic,
    article: dict,
    config: dict,
) -> Optional[dict]:
    """Score an article's relevance using Claude Haiku."""
    scoring_cfg = config.get("scoring", {})
    model = scoring_cfg.get("model", "claude-haiku-4-5-20251001")
    max_tokens = scoring_cfg.get("max_tokens", 100)
    profile = scoring_cfg.get("profile", "General AI news relevance.")

    try:
        prompt = SCORING_TEMPLATE.format(
            profile=profile.strip(),
            title=article["title"],
            source=article["source"],
            summary=article["summary"][:300],
        )

        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()

        # Strip markdown code blocks (Haiku sometimes wraps JSON in ```json...```)
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*$", "", text)
        text = text.strip()

        # Parse JSON
        if text.startswith("{"):
            result = json.loads(text)
        else:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                result = json.loads(match.group())
            else:
                log.warning(f"  Unparseable response for: {article['title'][:50]}")
                return None

        article["relevance_score"] = result.get("score", 0)
        article["relevance_reason"] = result.get("reason", "")
        article["tags"] = result.get("tags", [])
        article["scored_at"] = datetime.now(timezone.utc).isoformat()
        article["hash"] = hashlib.md5(
            f"{article['title']}:{article['source']}".encode()
        ).hexdigest()[:12]

        return article

    except Exception as e:
        log.warning(f"  Scoring failed for '{article['title'][:40]}': {e}")
        return None


# ---------------------------------------------------------------------------
# Storage backends
# ---------------------------------------------------------------------------

def _save_gcs(articles: list[dict], date_str: str, config: dict):
    """Save to Google Cloud Storage."""
    from google.cloud import storage as gcs

    storage_cfg = config.get("storage", {})
    bucket_name = storage_cfg.get("gcs_bucket", "gl-ai-news")
    prefix = storage_cfg.get("gcs_prefix", "scans")

    client = gcs.Client()
    bucket = client.bucket(bucket_name)

    # Daily scan
    blob_path = f"{prefix}/{date_str}.json"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(articles, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
    log.info(f"Saved {len(articles)} articles to gs://{bucket_name}/{blob_path}")

    # Latest pointer
    if config.get("output", {}).get("write_latest", True):
        latest_blob = bucket.blob(f"{prefix}/latest.json")
        latest_blob.upload_from_string(
            json.dumps({
                "date": date_str,
                "count": len(articles),
                "articles": articles,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2, ensure_ascii=False),
            content_type="application/json",
        )


def _save_local(articles: list[dict], date_str: str, config: dict):
    """Save to local filesystem (for dev/test)."""
    storage_cfg = config.get("storage", {})
    base_path = Path(storage_cfg.get("local_path", "./output"))
    base_path.mkdir(parents=True, exist_ok=True)

    # Daily scan
    out_file = base_path / f"{date_str}.json"
    out_file.write_text(
        json.dumps(articles, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info(f"Saved {len(articles)} articles to {out_file}")

    # Latest pointer
    if config.get("output", {}).get("write_latest", True):
        latest_file = base_path / "latest.json"
        latest_file.write_text(
            json.dumps({
                "date": date_str,
                "count": len(articles),
                "articles": articles,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def save_articles(articles: list[dict], date_str: str, config: dict):
    """Route to the configured storage backend."""
    backend = config.get("storage", {}).get("backend", "local")
    if backend == "gcs":
        _save_gcs(articles, date_str, config)
    else:
        _save_local(articles, date_str, config)


def load_recent_hashes(date_str: str, config: dict) -> set[str]:
    """Load hashes from recent scans for dedup."""
    storage_cfg = config.get("storage", {})
    backend = storage_cfg.get("backend", "local")
    dedup_days = storage_cfg.get("dedup_days", 3)
    hashes: set[str] = set()

    for days_ago in range(1, dedup_days + 1):
        d = datetime.now(timezone.utc) - timedelta(days=days_ago)
        d_str = d.strftime("%Y-%m-%d")

        try:
            if backend == "gcs":
                from google.cloud import storage as gcs
                bucket_name = storage_cfg.get("gcs_bucket", "gl-ai-news")
                prefix = storage_cfg.get("gcs_prefix", "scans")
                client = gcs.Client()
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(f"{prefix}/{d_str}.json")
                if blob.exists():
                    data = json.loads(blob.download_as_text())
                    for art in data:
                        if "hash" in art:
                            hashes.add(art["hash"])
            else:
                base_path = Path(storage_cfg.get("local_path", "./output"))
                f = base_path / f"{d_str}.json"
                if f.exists():
                    data = json.loads(f.read_text(encoding="utf-8"))
                    for art in data:
                        if "hash" in art:
                            hashes.add(art["hash"])
        except Exception:
            pass

    log.info(f"Loaded {len(hashes)} hashes for dedup (last {dedup_days} days)")
    return hashes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(config_path: str = None):
    config = load_config(config_path)

    start = datetime.now(timezone.utc)
    date_str = start.strftime("%Y-%m-%d")
    hours_lookback = config.get("fetch", {}).get("hours_lookback", 26)
    cutoff = start - timedelta(hours=hours_lookback)
    threshold = config.get("scoring", {}).get("threshold", 7)
    sources = get_enabled_sources(config)

    log.info(f"=== AI News Scanner — {date_str} ===")
    log.info(f"Sources: {len(sources)} | Threshold: {threshold}/10 | Lookback: {hours_lookback}h")

    # 1. Fetch
    log.info("--- Phase 1: Fetch RSS ---")
    all_articles = []
    for source in sources:
        articles = fetch_articles(source, cutoff, config)
        all_articles.extend(articles)
    log.info(f"Total fetched: {len(all_articles)}")

    if not all_articles:
        log.info("No new articles. Done.")
        return

    # 2. Dedup
    log.info("--- Phase 2: Dedup ---")
    recent_hashes = load_recent_hashes(date_str, config)
    for art in all_articles:
        art["hash"] = hashlib.md5(
            f"{art['title']}:{art['source']}".encode()
        ).hexdigest()[:12]

    pre_dedup = len(all_articles)
    all_articles = [a for a in all_articles if a["hash"] not in recent_hashes]
    log.info(f"After dedup: {len(all_articles)} (removed {pre_dedup - len(all_articles)})")

    # 3. Score
    log.info("--- Phase 3: Scoring ---")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set. Cannot score articles.")
        return

    client = anthropic.Anthropic(api_key=api_key)
    scored = []

    for article in all_articles:
        result = score_article(client, article, config)
        if result:
            scored.append(result)
            icon = ">" if result["relevance_score"] >= threshold else " "
            log.info(f"  {icon} [{result['relevance_score']}/10] {result['title'][:60]}")

    # 4. Filter
    relevant = [a for a in scored if a["relevance_score"] >= threshold]
    relevant.sort(key=lambda x: x["relevance_score"], reverse=True)

    log.info("--- Results ---")
    log.info(f"Scored: {len(scored)} | Relevant: {len(relevant)} | Filtered: {len(scored) - len(relevant)}")

    # 5. Save
    if relevant:
        log.info("--- Phase 4: Save ---")
        save_articles(relevant, date_str, config)

    # 6. Report
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    est_input_tokens = len(scored) * 250
    est_output_tokens = len(scored) * 30
    est_cost = (est_input_tokens * 0.25 / 1_000_000) + (est_output_tokens * 1.25 / 1_000_000)

    log.info(f"=== Done in {elapsed:.1f}s | Cost: ~${est_cost:.4f} ===")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI News Scanner")
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to config.yaml (default: ./config.yaml or CONFIG_PATH env)",
    )
    args = parser.parse_args()
    main(config_path=args.config)
