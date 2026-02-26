# BCI Lead Pauser — Local Worker

Runs on your Windows machine. When anyone clicks "Pause All Leads" in the Chrome extension,
this worker picks up the job and automates the actual pausing on provider portals.

## Quick Start

1. Open a terminal in this folder
2. Double-click `START.bat` (or run `python worker.py`)
3. The worker will:
   - Launch a Chrome browser (visible, so you can watch)
   - Poll ORBIT every 5 seconds for pause/unpause jobs
   - When a job comes in, log into each provider and click pause/resume

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Configuration

Edit `config.env` with your provider credentials. This file stays local — never committed to git.

## Supported Providers

- ✅ All Web Leads (AWL) — fully automated
- 🔜 QuoteWizard — coming next
- 🔜 InsuranceAgents.ai — coming next

## How It Works

1. Agent clicks "Pause All" in Chrome extension
2. Extension calls ORBIT API → creates automation job
3. This worker picks up the job
4. Playwright opens browser, logs into each provider, clicks pause
5. Reports results back to ORBIT
6. Extension updates to show "All Paused"
