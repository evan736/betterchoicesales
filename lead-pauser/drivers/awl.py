"""
All Web Leads — Playwright automation driver.

Pause flow:
  1. Login at secure.allwebleads.com/login (Username + Password → Log In)
  2. Navigate to secure.allwebleads.com/Leads/Pause
  3. If "Leads are active" → click "Pause" button
  4. If "Calls are paused" → already paused, skip

Unpause flow:
  1. Login (same)
  2. Navigate to secure.allwebleads.com/Leads/Pause
  3. If "Calls are paused" → click "Resume" button
  4. If "Leads are active" → already active, skip
"""
import logging
from playwright.async_api import Page

logger = logging.getLogger("lead-pauser.awl")

LOGIN_URL = "https://secure.allwebleads.com/login?returnUrl=%2f"
PAUSE_URL = "https://secure.allwebleads.com/Leads/Pause"


async def login(page: Page, username: str, password: str) -> bool:
    """Login to All Web Leads. Returns True on success."""
    try:
        await page.goto(LOGIN_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Fill username
        username_input = page.locator('input[name="Username"]').first
        if await username_input.count() == 0:
            username_input = page.locator('input[type="text"]').first
        await username_input.fill(username)

        # Fill password
        password_input = page.locator('input[name="Password"]').first
        if await password_input.count() == 0:
            password_input = page.locator('input[type="password"]').first
        await password_input.fill(password)

        # Click login
        login_btn = page.locator('input[value="Log In"]').first
        if await login_btn.count() == 0:
            login_btn = page.locator('button:has-text("Log In")').first
        if await login_btn.count() == 0:
            login_btn = page.locator('input[type="submit"]').first
        await login_btn.click()

        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Check if we landed on the dashboard (logged in)
        if "login" not in page.url.lower():
            logger.info("AWL: Login successful")
            return True
        else:
            logger.error(f"AWL: Login may have failed, still on {page.url}")
            return False
    except Exception as e:
        logger.error(f"AWL: Login failed: {e}")
        return False


async def pause(page: Page, username: str, password: str) -> dict:
    """Pause leads and calls on All Web Leads."""
    try:
        if not await login(page, username, password):
            return {"success": False, "error": "Login failed"}

        await page.goto(PAUSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        content = await page.content()

        if "Leads are active" in content:
            pause_btn = page.locator('button:has-text("Pause"), input[value="Pause"]').first
            if await pause_btn.count() == 0:
                pause_btn = page.locator('a:has-text("Pause")').first
            if await pause_btn.count() > 0:
                await pause_btn.click()
                await page.wait_for_timeout(3000)
                logger.info("AWL: Paused successfully")
                return {"success": True, "action": "paused"}
            return {"success": False, "error": "Pause button not found"}

        elif "paused" in content.lower():
            logger.info("AWL: Already paused")
            return {"success": True, "action": "already_paused"}
        else:
            logger.warning(f"AWL: Unknown state on pause page")
            return {"success": False, "error": "Unknown page state"}

    except Exception as e:
        logger.error(f"AWL pause error: {e}")
        return {"success": False, "error": str(e)}


async def unpause(page: Page, username: str, password: str) -> dict:
    """Resume leads and calls on All Web Leads."""
    try:
        if not await login(page, username, password):
            return {"success": False, "error": "Login failed"}

        await page.goto(PAUSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        content = await page.content()

        if "paused" in content.lower():
            resume_btn = page.locator('button:has-text("Resume"), input[value="Resume"]').first
            if await resume_btn.count() == 0:
                resume_btn = page.locator('a:has-text("Resume")').first
            if await resume_btn.count() > 0:
                await resume_btn.click()
                await page.wait_for_timeout(3000)
                logger.info("AWL: Resumed successfully")
                return {"success": True, "action": "resumed"}
            return {"success": False, "error": "Resume button not found"}

        elif "Leads are active" in content:
            logger.info("AWL: Already active")
            return {"success": True, "action": "already_active"}
        else:
            return {"success": False, "error": "Unknown page state"}

    except Exception as e:
        logger.error(f"AWL unpause error: {e}")
        return {"success": False, "error": str(e)}
