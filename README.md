# AI News Scanner

Intelligent RSS aggregator with LLM-powered relevance scoring. Scans 21 AI news sources daily, scores each article against your professional profile using Claude Haiku, and saves only what's relevant to you.

Built as a Cloud Run Job for daily automation. Cost: ~$0.003/execution.

## How it works

```
21 RSS/Atom feeds → fetch articles → dedup (last 3 days) → Claude Haiku scoring → filter (≥7/10) → save to GCS or local
```

Each article gets scored 1-10 against a customizable relevance profile. Only articles above your threshold are saved. Previous scans are used for deduplication.

## Sources (21 default)

| Category | Sources |
|----------|---------|
| **AI Labs** | OpenAI, Google AI, Hugging Face, Microsoft AI |
| **Tech Media** | MIT Tech Review, The Verge AI, Ars Technica, TechCrunch |
| **Newsletters** | Simon Willison, Latent Space, Import AI (Jack Clark) |
| **Research** | arXiv cs.AI |
| **Developer** | KDnuggets, Machine Learning Mastery |
| **EU Policy** | Politico EU |
| **Italia** | AI4Business, Agenda Digitale, StartupItalia, Wired Italia, Ninja Marketing, Key4biz |

Add, remove, or disable sources in `config.yaml`. No code changes needed.

## Quick start

### Prerequisites

- Python 3.10+
- [Anthropic API key](https://console.anthropic.com/)

### Local setup

```bash
git clone https://github.com/videomakingio/ai-news-scanner.git
cd ai-news-scanner

pip install -r requirements.txt

# Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Run with local storage (no GCS needed)
python scanner.py
```

By default, the scanner saves to `./output/`. Articles are stored as JSON files named by date (`2026-03-31.json`).

### Custom config

```bash
# Copy and edit the config
cp config.yaml my-config.yaml
# Edit my-config.yaml to change sources, scoring profile, etc.

# Run with custom config
python scanner.py --config my-config.yaml

# Or use the environment variable
CONFIG_PATH=my-config.yaml python scanner.py
```

## Configuration

Everything is in `config.yaml`. The key sections:

### Scoring profile

The `scoring.profile` field tells Claude who you are and what matters to you. Claude uses this to score articles 1-10. Change it to match your domain:

```yaml
scoring:
  threshold: 7
  profile: |
    You are a relevance filter for a DevOps engineer focused on
    Kubernetes, observability, and platform engineering.

    High relevance (8-10):
    - Kubernetes releases and best practices
    - Observability tools (Prometheus, Grafana, OpenTelemetry)
    - Platform engineering case studies
    ...
```

### Sources

Add any RSS/Atom feed:

```yaml
sources:
  - name: "My Favorite Blog"
    url: "https://example.com/feed.xml"
    lang: "en"
    category: "custom"
    enabled: true
```

Disable without removing:

```yaml
  - name: "arXiv cs.AI"
    url: "https://arxiv.org/rss/cs.AI"
    enabled: false  # skip this source
```

### Storage

Two backends: Google Cloud Storage (for production) or local filesystem (for dev/test).

```yaml
storage:
  backend: "local"      # "gcs" or "local"
  local_path: "./output"

  # GCS settings (only used when backend: "gcs")
  gcs_bucket: "my-bucket"
  gcs_prefix: "scans"
```

## Deploy to Cloud Run

For daily automated scans:

```bash
# Edit deploy.sh with your GCP project ID
chmod +x deploy.sh
./deploy.sh
```

This creates:
1. A GCS bucket for storing scan results
2. A Cloud Run Job running the scanner
3. A Cloud Scheduler trigger (daily at 7:00 CET)

### Prerequisites for Cloud Run

- `gcloud` CLI authenticated
- GCP project with Cloud Run, Cloud Scheduler, and Secret Manager enabled
- Anthropic API key stored in Secret Manager:
  ```bash
  echo -n "sk-ant-..." | gcloud secrets create anthropic-api-key --data-file=-
  ```

## Output format

Each scan produces a JSON file:

```json
[
  {
    "title": "Claude 4 released with advanced reasoning",
    "url": "https://...",
    "summary": "Anthropic announced...",
    "source": "MIT Tech Review AI",
    "category": "media",
    "lang": "en",
    "published": "2026-03-31T08:00:00+00:00",
    "relevance_score": 9,
    "relevance_reason": "Major Claude release, core tool",
    "tags": ["claude", "anthropic", "llm"],
    "scored_at": "2026-03-31T07:15:23+00:00",
    "hash": "a1b2c3d4e5f6"
  }
]
```

A `latest.json` file is also maintained with the most recent scan results for quick access.

## Cost

Using Claude Haiku for scoring:
- ~150 articles/day = ~37,500 input tokens + ~4,500 output tokens
- **~$0.003/day** (~$0.09/month)
- Cloud Run Job: free tier covers this easily

## Examples

### Filter by category

```python
import json

with open("output/2026-03-31.json") as f:
    articles = json.load(f)

# Only Italian sources
italian = [a for a in articles if a["lang"] == "it"]

# Only lab announcements
labs = [a for a in articles if a["category"] == "lab"]

# Top 5 by score
top5 = sorted(articles, key=lambda x: x["relevance_score"], reverse=True)[:5]
```

### Use as a module

```python
from scanner import load_config, get_enabled_sources, fetch_articles
from datetime import datetime, timedelta, timezone

config = load_config("config.yaml")
sources = get_enabled_sources(config)
cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

for source in sources:
    articles = fetch_articles(source, cutoff, config)
    for a in articles:
        print(f"[{a['source']}] {a['title']}")
```

## License

MIT

## Author

Giovanni Liguori — [giovanniliguori.it](https://giovanniliguori.it)
