# 📊 Notion IPO Tracker

Automated tracker that pulls live **IPO Grey Market Premium (GMP)** data and
synces it into a [Notion](https://www.notion.so/) database on a schedule.

## ✨ What it does

- Scrapes the latest IPO GMP table from IPOWatch
- Matches each IPO against your Notion database rows (by name)
- Updates the GMP / listing gain / status fields automatically
- Runs on GitHub Actions (`.github/workflows/ipo_sync.yml`) — no server needed

## ⚙️ Setup

1. Create a Notion integration and share your IPO database with it.
2. Set the `NOTION_TOKEN` secret in your repo settings.
3. Update `DATABASE_ID` in `check_ipos.py` to your database id.
4. The workflow runs on its configured schedule and updates Notion.

```bash
# Run locally
export NOTION_TOKEN="ntn_..."
python check_ipos.py
```

## 📁 Files

| File | Purpose |
|------|---------|
| `check_ipos.py` | Core sync script (Notion API + GMP scrape) |
| `.github/workflows/ipo_sync.yml` | Scheduled GitHub Actions runner |

> Requires Python 3.8+ and network access to `api.notion.com` and `ipowatch.in`.
