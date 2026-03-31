"""AI News Scanner — Intelligent RSS aggregator with LLM-powered relevance scoring.

Scans configurable RSS/Atom sources, scores each article against your
professional profile using an LLM (Anthropic Claude, OpenAI, or Google Gemini),
and saves only what matters.

Supported LLM providers:
- Anthropic (Claude Haiku) — default, ~$0.003/run
- OpenAI (GPT-4o-mini) — ~$0.005/run
- Google Gemini (Flash) — free tier available

Deploy as a Cloud Run Job with Cloud Scheduler for daily automation.

GitHub: github.com/videomakingio-gif/ai-news-scanner
License: MIT
"""

import os
import re
import json
import time
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Callable
from urllib.request import Request, urlopen

import yaml
import feedparser

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
# LLM Scoring (Multi-provider: Anthropic, OpenAI, Gemini)
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


def _call_anthropic(prompt: str, config: dict) -> str:
    """Call Anthropic Claude API."""
    import anthropic
    scoring_cfg = config.get("scoring", {})
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=scoring_cfg.get("model", "claude-haiku-4-5-20251001"),
        max_tokens=scoring_cfg.get("max_tokens", 100),
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _call_openai(prompt: str, config: dict) -> str:
    """Call OpenAI API."""
    import openai
    scoring_cfg = config.get("scoring", {})
    api_key = os.environ.get("OPENAI_API_KEY")
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=scoring_cfg.get("model", "gpt-4o-mini"),
        max_tokens=scoring_cfg.get("max_tokens", 100),
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


def _call_gemini(prompt: str, config: dict) -> str:
    """Call Google Gemini API."""
    from google import genai
    scoring_cfg = config.get("scoring", {})
    api_key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY"))
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=scoring_cfg.get("model", "gemini-2.0-flash"),
        contents=prompt,
    )
    return response.text.strip()


def _create_llm_caller(config: dict) -> Callable[[str, dict], str]:
    """Create an LLM caller function based on the configured provider."""
    provider = config.get("scoring", {}).get("provider", "anthropic")
    callers = {
        "anthropic": _call_anthropic,
        "openai": _call_openai,
        "gemini": _call_gemini,
    }
    if provider not in callers:
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            f"Supported: {', '.join(callers.keys())}"
        )
    return callers[provider]


def _call_with_retry(
    caller: Callable, prompt: str, config: dict,
    max_retries: int = 3, base_delay: float = 1.0,
) -> str:
    """Call LLM with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            return caller(prompt, config)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            log.warning(f"  LLM call failed (attempt {attempt + 1}/{max_retries}): {e}")
            log.warning(f"  Retrying in {delay:.1f}s...")
            time.sleep(delay)


def _parse_llm_response(text: str) -> Optional[dict]:
    """Parse JSON from LLM response, handling markdown wrapping."""
    # Strip markdown code blocks
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    if text.startswith("{"):
        return json.loads(text)

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())

    return None


def score_article(
    client,  # kept for backward compatibility, can be None with new providers
    article: dict,
    config: dict,
    llm_caller: Callable = None,
) -> Optional[dict]:
    """Score an article's relevance using the configured LLM provider."""
    scoring_cfg = config.get("scoring", {})
    profile = scoring_cfg.get("profile", "General AI news relevance.")

    try:
        prompt = SCORING_TEMPLATE.format(
            profile=profile.strip(),
            title=article["title"],
            source=article["source"],
            summary=article["summary"][:300],
        )

        # Use provided caller or fall back to direct Anthropic (backward compat)
        if llm_caller:
            text = _call_with_retry(llm_caller, prompt, config)
        else:
            import anthropic
            if client is None:
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=scoring_cfg.get("model", "claude-haiku-4-5-20251001"),
                max_tokens=scoring_cfg.get("max_tokens", 100),
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

        result = _parse_llm_response(text)
        if result is None:
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
# Notifications (Telegram, Slack)
# ---------------------------------------------------------------------------

def _send_telegram(articles: list[dict], config: dict):
    """Send scan results to Telegram."""
    tg_cfg = config.get("notifications", {}).get("telegram", {})
    bot_token = tg_cfg.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    chat_id = tg_cfg.get("chat_id", os.environ.get("TELEGRAM_CHAT_ID", ""))

    if not bot_token or not chat_id:
        return

    # Build message
    lines = [f"📰 <b>AI News Scanner</b> — {len(articles)} articoli rilevanti\n"]
    for a in articles[:10]:  # Max 10 articles per message
        score = a.get('relevance_score', 0)
        stars = '⭐' * min(score, 10)
        lines.append(
            f"\n<b>[{score}/10]</b> {stars}\n"
            f"<a href=\"{a['url']}\">{a['title']}</a>\n"
            f"<i>{a.get('relevance_reason', '')}</i> — {a['source']}"
        )

    text = "\n".join(lines)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    try:
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        urlopen(req, timeout=10)
        log.info(f"  Telegram: sent {len(articles)} articles to chat {chat_id}")
    except Exception as e:
        log.warning(f"  Telegram notification failed: {e}")


def _send_slack(articles: list[dict], config: dict):
    """Send scan results to Slack via webhook."""
    slack_cfg = config.get("notifications", {}).get("slack", {})
    webhook_url = slack_cfg.get("webhook_url", os.environ.get("SLACK_WEBHOOK_URL", ""))

    if not webhook_url:
        return

    # Build Slack Block Kit message
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📰 AI News Scanner — {len(articles)} articoli rilevanti"}
        }
    ]

    for a in articles[:10]:
        score = a.get('relevance_score', 0)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*[{score}/10]* <{a['url']}|{a['title']}>\n"
                    f"_{a.get('relevance_reason', '')}_ — {a['source']}"
                ),
            }
        })

    payload = json.dumps({"blocks": blocks}).encode("utf-8")

    try:
        req = Request(webhook_url, data=payload, headers={"Content-Type": "application/json"})
        urlopen(req, timeout=10)
        log.info(f"  Slack: sent {len(articles)} articles")
    except Exception as e:
        log.warning(f"  Slack notification failed: {e}")


def send_notifications(articles: list[dict], config: dict):
    """Send notifications to all configured channels."""
    notif_cfg = config.get("notifications", {})
    if not notif_cfg or not articles:
        return

    log.info("--- Phase 5: Notifications ---")

    if notif_cfg.get("telegram", {}).get("enabled", False):
        _send_telegram(articles, config)

    if notif_cfg.get("slack", {}).get("enabled", False):
        _send_slack(articles, config)


# ---------------------------------------------------------------------------
# Rich output helpers (used only with --rich flag)
# ---------------------------------------------------------------------------

BANNER = r"""
[bold cyan]
    _    ___   _   _                     ____
   / \  |_ _| | \ | | _____      _____  / ___|  ___ __ _ _ __  _ __   ___ _ __
  / _ \  | |  |  \| |/ _ \ \ /\ / / __| \___ \ / __/ _` | '_ \| '_ \ / _ \ '__|
 / ___ \ | |  | |\  |  __/\ V  V /\__ \  ___) | (_| (_| | | | | | | |  __/ |
/_/   \_\___| |_| \_|\___| \_/\_/ |___/ |____/ \___\__,_|_| |_|_| |_|\___|_|
[/bold cyan]
[dim]Intelligent RSS aggregator with LLM-powered relevance scoring[/dim]
"""


def _score_color(score: int) -> str:
    """Return rich color tag based on score."""
    if score >= 8:
        return "bold green"
    elif score >= 7:
        return "green"
    elif score >= 5:
        return "yellow"
    elif score >= 3:
        return "dim yellow"
    else:
        return "dim red"


def _score_bar(score: int) -> str:
    """Return a visual bar for the score (e.g. '████████░░')."""
    return "█" * score + "░" * (10 - score)


def _main_rich(config_path: str = None):
    """Run the scanner with Rich terminal output (for local use / demos)."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
        from rich.rule import Rule
        from rich import box
    except ImportError:
        print("Error: 'rich' is not installed. Run: pip install rich")
        raise SystemExit(1)

    console = Console()

    # Banner
    console.print(BANNER)
    console.print()

    # Config
    config = load_config(config_path)
    sources = get_enabled_sources(config)
    threshold = config.get("scoring", {}).get("threshold", 7)
    hours_lookback = config.get("fetch", {}).get("hours_lookback", 26)
    provider = config.get("scoring", {}).get("provider", "anthropic")
    model = config.get("scoring", {}).get("model", "claude-haiku-4-5-20251001")

    start = datetime.now(timezone.utc)
    date_str = start.strftime("%Y-%m-%d")
    cutoff = start - timedelta(hours=hours_lookback)

    cfg_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    cfg_table.add_column("Key", style="dim")
    cfg_table.add_column("Value", style="bold")
    cfg_table.add_row("Date", date_str)
    cfg_table.add_row("Sources", str(len(sources)))
    cfg_table.add_row("Provider", f"{provider} ({model})")
    cfg_table.add_row("Threshold", f"{threshold}/10")
    cfg_table.add_row("Lookback", f"{hours_lookback}h")
    cfg_table.add_row("Storage", config.get("storage", {}).get("backend", "local"))
    console.print(Panel(cfg_table, title="[bold]Configuration[/bold]", border_style="cyan"))
    console.print()

    # Phase 1: Fetch
    console.print(Rule("[bold cyan]Phase 1: Fetch RSS[/bold cyan]"))
    console.print()
    all_articles = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30),
        TextColumn("[bold]{task.completed}/{task.total}[/bold]"),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching feeds...", total=len(sources))
        for source in sources:
            articles = fetch_articles(source, cutoff, config)
            all_articles.extend(articles)
            status = f"[green]+{len(articles)}[/green]" if articles else "[dim]0[/dim]"
            progress.update(task, advance=1, description=f"  {source['name'][:30]:<30} {status}")

    console.print()
    console.print(f"  [bold]{len(all_articles)}[/bold] articles fetched from [bold]{len(sources)}[/bold] sources")
    console.print()

    if not all_articles:
        console.print("[yellow]No new articles found. Done.[/yellow]")
        return

    # Phase 2: Dedup
    console.print(Rule("[bold cyan]Phase 2: Dedup[/bold cyan]"))
    console.print()
    recent_hashes = load_recent_hashes(date_str, config)
    for art in all_articles:
        art["hash"] = hashlib.md5(
            f"{art['title']}:{art['source']}".encode()
        ).hexdigest()[:12]
    pre_dedup = len(all_articles)
    all_articles = [a for a in all_articles if a["hash"] not in recent_hashes]
    removed = pre_dedup - len(all_articles)
    console.print(f"  Previous hashes loaded: [bold]{len(recent_hashes)}[/bold]")
    console.print(f"  Duplicates removed:     [bold red]{removed}[/bold red]")
    console.print(f"  Articles to score:      [bold green]{len(all_articles)}[/bold green]")
    console.print()

    if not all_articles:
        console.print("[yellow]All articles already seen. Done.[/yellow]")
        return

    # Phase 3: Score
    console.print(Rule("[bold cyan]Phase 3: LLM Scoring[/bold cyan]"))
    console.print()

    api_key = _get_api_key_for_provider(provider)
    if not api_key:
        env_var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
        console.print(f"[bold red]{env_var.get(provider, 'API_KEY')} not set. Cannot score articles.[/bold red]")
        return

    try:
        llm_caller = _create_llm_caller(config)
    except Exception as e:
        console.print(f"[bold red]Error creating LLM caller: {e}[/bold red]")
        return

    scored = []
    relevant = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30),
        TextColumn("[bold]{task.completed}/{task.total}[/bold]"),
        console=console,
    ) as progress:
        task = progress.add_task("Scoring articles...", total=len(all_articles))
        for article in all_articles:
            result = score_article(None, article, config, llm_caller=llm_caller)
            if result:
                scored.append(result)
                s = result["relevance_score"]
                color = _score_color(s)
                icon = "✓" if s >= threshold else "·"
                progress.update(
                    task, advance=1,
                    description=f"  [{color}]{icon} [{s:>2}/10][/{color}] {result['title'][:55]}"
                )
                if s >= threshold:
                    relevant.append(result)
            else:
                progress.update(task, advance=1, description=f"  [dim]? [--/10] {article['title'][:55]}[/dim]")

    relevant.sort(key=lambda x: x["relevance_score"], reverse=True)
    console.print()

    # Results
    console.print(Rule("[bold cyan]Results[/bold cyan]"))
    console.print()

    stats = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    stats.add_column("Metric", style="dim")
    stats.add_column("Value", style="bold")
    stats.add_row("Articles scored", str(len(scored)))
    stats.add_row(f"Relevant (≥ {threshold}/10)", f"[bold green]{len(relevant)}[/bold green]")
    stats.add_row("Filtered out", str(len(scored) - len(relevant)))
    console.print(Panel(stats, title="[bold]Summary[/bold]", border_style="green"))
    console.print()

    if relevant:
        tbl = Table(
            title=f"[bold green]Top Articles ({len(relevant)})[/bold green]",
            box=box.ROUNDED, show_lines=True, padding=(0, 1),
        )
        tbl.add_column("Score", justify="center", width=12, no_wrap=True)
        tbl.add_column("Source", style="cyan", width=20, no_wrap=True)
        tbl.add_column("Title", width=50)
        tbl.add_column("Tags", style="dim", width=20)
        tbl.add_column("Why", style="dim italic", width=25)
        for art in relevant:
            s = art["relevance_score"]
            color = _score_color(s)
            tbl.add_row(
                f"[{color}]{_score_bar(s)} {s}/10[/{color}]",
                art["source"][:20],
                art["title"][:50],
                ", ".join(art.get("tags", []))[:20],
                art.get("relevance_reason", "")[:25],
            )
        console.print(tbl)
        console.print()

    filtered = [a for a in scored if a["relevance_score"] < threshold]
    if filtered:
        console.print(f"  [dim]Filtered out ({len(filtered)} articles below threshold):[/dim]")
        for art in filtered[:5]:
            s = art["relevance_score"]
            color = _score_color(s)
            console.print(f"    [{color}]{s}/10[/{color}]  [dim]{art['source'][:15]:<15}[/dim]  {art['title'][:60]}")
        if len(filtered) > 5:
            console.print(f"    [dim]... and {len(filtered) - 5} more[/dim]")
        console.print()

    # Phase 4: Save
    if relevant:
        console.print(Rule("[bold cyan]Phase 4: Save[/bold cyan]"))
        console.print()
        save_articles(relevant, date_str, config)
        backend = config.get("storage", {}).get("backend", "local")
        if backend == "local":
            out_path = Path(config.get("storage", {}).get("local_path", "./output"))
            console.print(f"  Saved to [bold]{out_path / f'{date_str}.json'}[/bold]")
        else:
            bucket = config.get("storage", {}).get("gcs_bucket", "")
            console.print(f"  Saved to [bold]gs://{bucket}/scans/{date_str}.json[/bold]")
        console.print()

    # Phase 5: Notify
    if relevant:
        send_notifications(relevant, config)

    # Final report
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    est_input = len(scored) * 250
    est_output = len(scored) * 30
    est_cost = (est_input * 0.25 / 1_000_000) + (est_output * 1.25 / 1_000_000)

    console.print(Rule("[bold cyan]Done[/bold cyan]"))
    console.print()
    final = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    final.add_column("", style="dim")
    final.add_column("", style="bold")
    final.add_row("Time", f"{elapsed:.1f}s")
    final.add_row("Cost", f"~${est_cost:.4f}")
    final.add_row("Sources", str(len(sources)))
    final.add_row("Scored", str(len(scored)))
    final.add_row("Saved", f"[bold green]{len(relevant)}[/bold green]")
    console.print(Panel(final, title="[bold]Execution Report[/bold]", border_style="cyan"))
    console.print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _get_api_key_for_provider(provider: str) -> Optional[str]:
    """Get the appropriate API key for the configured provider."""
    key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    env_var = key_map.get(provider, "ANTHROPIC_API_KEY")
    # Gemini also accepts GOOGLE_API_KEY
    if provider == "gemini":
        return os.environ.get(env_var) or os.environ.get("GOOGLE_API_KEY")
    return os.environ.get(env_var)


def main(config_path: str = None, use_rich: bool = False):
    if use_rich:
        _main_rich(config_path)
        return

    config = load_config(config_path)

    start = datetime.now(timezone.utc)
    date_str = start.strftime("%Y-%m-%d")
    hours_lookback = config.get("fetch", {}).get("hours_lookback", 26)
    cutoff = start - timedelta(hours=hours_lookback)
    threshold = config.get("scoring", {}).get("threshold", 7)
    provider = config.get("scoring", {}).get("provider", "anthropic")
    sources = get_enabled_sources(config)

    log.info(f"=== AI News Scanner — {date_str} ===")
    log.info(f"Sources: {len(sources)} | Threshold: {threshold}/10 | Provider: {provider} | Lookback: {hours_lookback}h")

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
    api_key = _get_api_key_for_provider(provider)
    if not api_key:
        env_var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
        log.error(f"{env_var.get(provider, 'API_KEY')} not set. Cannot score articles.")
        return

    llm_caller = _create_llm_caller(config)
    scored = []

    for article in all_articles:
        result = score_article(None, article, config, llm_caller=llm_caller)
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

    # 6. Notify
    if relevant:
        send_notifications(relevant, config)

    # 7. Report
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
    parser.add_argument(
        "--rich", "-r",
        action="store_true",
        help="Rich terminal output with progress bars and tables (requires: pip install rich)",
    )
    args = parser.parse_args()
    main(config_path=args.config, use_rich=args.rich)
