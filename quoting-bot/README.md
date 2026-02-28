# ORBIT Quoting Bot — National General

Browser automation that logs into the NatGen agent portal and fills out quote forms automatically using lead data from ORBIT.

## Setup (Local Machine)

```bash
cd quoting-bot
pip install -r requirements.txt
playwright install chromium
```

## Configure

Copy `.env.example` to `.env` and fill in your NatGen portal credentials:

```bash
cp .env.example .env
# Edit .env with your NatGen login + ORBIT API credentials
```

## Usage

```bash
# Test your NatGen login
python bot.py test-login

# Interactive screenshot mode (map the portal)
python bot.py screenshot

# Quote a lead from ORBIT
python bot.py quote --lead-id 123

# Manual quote entry
python bot.py quote --manual
```

## How It Works

1. Bot launches a visible Chrome browser on your machine
2. Logs into NatGen agent portal with your credentials
3. Navigates to new quote
4. Fills in all fields from ORBIT lead data (or manual entry)
5. Submits the quote and captures the premium
6. Saves the result back to ORBIT
7. Screenshots every step for audit trail

## Status

🟡 **Framework built** — waiting for NatGen portal field mapping.

The bot skeleton is ready. Once we map every field on every screen of the NatGen portal, we fill in the Playwright selectors and the bot is live.
