"""
BCI Lead Pauser — Local Worker

Runs on Evan's Windows machine. Polls ORBIT for pause/unpause jobs,
then uses Playwright to automate provider portals.

Usage:
  pip install -r requirements.txt
  playwright install chromium
  python worker.py
"""
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import httpx

# ── Setup logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("lead-pauser")

# ── Load config ──────────────────────────────────────────────────
def load_config():
    config = {}
    env_path = Path(__file__).parent / "config.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                config[key.strip()] = val.strip().strip('"').strip("'")
    return config

CONFIG = load_config()
ORBIT_API = CONFIG.get("ORBIT_API", "https://better-choice-api.onrender.com")
POLL_INTERVAL = int(CONFIG.get("POLL_INTERVAL", "5"))

# ── Provider drivers ─────────────────────────────────────────────
PROVIDERS = {
    "allwebleads": {
        "module": "drivers.awl",
        "username_key": "AWL_USERNAME",
        "password_key": "AWL_PASSWORD",
    },
    # Future:
    # "quotewizard": { "module": "drivers.quotewizard", ... },
    # "insuranceagents-ai": { "module": "drivers.insuranceagents", ... },
}


async def run_provider(slug: str, action: str, browser) -> dict:
    """Run pause/unpause for a single provider."""
    prov = PROVIDERS.get(slug)
    if not prov:
        return {"success": False, "error": f"No driver for {slug}", "skipped": True}

    username = CONFIG.get(prov["username_key"], "")
    password = CONFIG.get(prov["password_key"], "")
    if not username or not password:
        return {"success": False, "error": f"No credentials for {slug}"}

    try:
        # Import the driver module
        mod = __import__(prov["module"], fromlist=["pause", "unpause"])

        # Create a new browser context with persistent cookies
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        if action == "pause_all":
            result = await mod.pause(page, username, password)
        else:
            result = await mod.unpause(page, username, password)

        await context.close()
        return result

    except Exception as e:
        logger.error(f"Driver error for {slug}: {e}")
        return {"success": False, "error": str(e)}


async def execute_job(job: dict, browser):
    """Execute a single automation job across all providers."""
    job_id = job["id"]
    action = job["action"]
    logger.info(f"═══ Executing job #{job_id}: {action} (by {job.get('requested_by', '?')}) ═══")

    # Claim the job
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(f"{ORBIT_API}/api/lead-providers/automation/jobs/{job_id}/claim")
            if resp.status_code != 200:
                logger.warning(f"Could not claim job #{job_id}: {resp.text}")
                return
        except Exception as e:
            logger.error(f"Failed to claim job #{job_id}: {e}")
            return

    # Run all provider drivers in parallel
    results = {}
    tasks = []
    for slug in PROVIDERS:
        tasks.append((slug, run_provider(slug, action, browser)))

    for slug, coro in tasks:
        result = await coro
        results[slug] = result
        status = "✅" if result.get("success") else "❌"
        logger.info(f"  {status} {slug}: {result.get('action', result.get('error', '?'))}")

    # Report results back to ORBIT
    overall = "completed" if all(r.get("success") for r in results.values()) else "failed"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            await client.post(
                f"{ORBIT_API}/api/lead-providers/automation/jobs/{job_id}/complete",
                json={"status": overall, "results": results},
            )
            logger.info(f"═══ Job #{job_id} {overall} ═══")
        except Exception as e:
            logger.error(f"Failed to report job #{job_id}: {e}")


async def poll_loop():
    """Main polling loop — checks ORBIT for pending jobs."""
    from playwright.async_api import async_playwright

    logger.info("╔══════════════════════════════════════════════╗")
    logger.info("║    BCI Lead Pauser — Local Worker v1.0      ║")
    logger.info("║    Polling ORBIT for pause/unpause jobs      ║")
    logger.info(f"║    API: {ORBIT_API:<36} ║")
    logger.info(f"║    Poll interval: {POLL_INTERVAL}s{' ' * 27}║")
    logger.info(f"║    Providers: {', '.join(PROVIDERS.keys()):<30} ║")
    logger.info("╚══════════════════════════════════════════════╝")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # Show browser so you can see what's happening
        )
        logger.info("Browser launched (headless=False — you can watch the automation)")

        while True:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"{ORBIT_API}/api/lead-providers/automation/pending")
                    if resp.status_code == 200:
                        data = resp.json()
                        jobs = data.get("jobs", [])
                        if jobs:
                            for job in jobs:
                                await execute_job(job, browser)
            except httpx.ConnectError:
                logger.debug("ORBIT unreachable, retrying...")
            except Exception as e:
                logger.error(f"Poll error: {e}")

            await asyncio.sleep(POLL_INTERVAL)


def main():
    print()
    print("  🚀 BCI Lead Pauser starting...")
    print("  Press Ctrl+C to stop")
    print()

    try:
        asyncio.run(poll_loop())
    except KeyboardInterrupt:
        print("\n  ⏹ Worker stopped.")


if __name__ == "__main__":
    main()
