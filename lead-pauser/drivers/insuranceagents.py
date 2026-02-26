"""
InsuranceAgents.ai — Playwright automation driver.

Pause flow:
  1. Login at portal.insuranceagents.ai/login (Email + Password → Log In)
  2. Navigate to Campaigns page (sidebar → Campaigns)
  3. For each campaign row: click the status dot / options to pause

Unpause flow:
  1. Login (same)
  2. Navigate to Campaigns page
  3. For each campaign row: click to activate

Campaign statuses from screenshots:
  - Green dot = active
  - Red dot = paused
  - Each row has a "..." Options menu
"""
import logging
from playwright.async_api import Page

logger = logging.getLogger("lead-pauser.insuranceagents")

LOGIN_URL = "https://portal.insuranceagents.ai/login"
CAMPAIGNS_URL = "https://portal.insuranceagents.ai/campaigns"


async def login(page: Page, email: str, password: str) -> bool:
    """Login to InsuranceAgents.ai."""
    try:
        await page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1000)

        await page.fill('input[type="email"], input[name="email"], input[placeholder*="mail" i]', email)
        await page.fill('input[type="password"], input[name="password"]', password)

        await page.click('button:has-text("Log In"), button:has-text("Login"), button[type="submit"]')
        await page.wait_for_load_state("networkidle", timeout=20000)
        await page.wait_for_timeout(2000)

        if "login" not in page.url.lower():
            logger.info("InsuranceAgents.ai: Login successful")
            return True

        logger.error(f"InsuranceAgents.ai: Login may have failed, on {page.url}")
        return False

    except Exception as e:
        logger.error(f"InsuranceAgents.ai: Login failed: {e}")
        return False


async def _get_campaign_rows(page: Page):
    """Get all campaign rows from the campaigns table."""
    await page.goto(CAMPAIGNS_URL, wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(2000)

    # The campaigns table has rows with: checkbox, Status dot, Name, Product, Type, etc.
    # Each row has a "..." options menu in the last column
    rows = page.locator('table tbody tr, [class*="campaign-row"], [class*="MuiTableRow"]')
    count = await rows.count()
    logger.info(f"InsuranceAgents.ai: Found {count} campaign rows")
    return rows, count


async def pause(page: Page, email: str, password: str) -> dict:
    """Pause all campaigns on InsuranceAgents.ai."""
    try:
        if not await login(page, email, password):
            return {"success": False, "error": "Login failed"}

        rows, count = await _get_campaign_rows(page)
        if count == 0:
            return {"success": False, "error": "No campaigns found"}

        paused_count = 0
        already_paused = 0

        for i in range(count):
            row = rows.nth(i)
            row_text = await row.inner_text()

            # Check if this campaign is already paused (red dot)
            # Look for status indicators
            status_dot = row.locator('[class*="status"], [class*="dot"], [class*="circle"]').first
            options_btn = row.locator('button:has-text("..."), [class*="options"], [class*="menu"], [aria-label*="option" i], td:last-child button').first

            if await options_btn.count() > 0:
                await options_btn.click()
                await page.wait_for_timeout(1000)

                # Look for Pause option in dropdown menu
                pause_option = page.locator('li:has-text("Pause"), button:has-text("Pause"), a:has-text("Pause"), [role="menuitem"]:has-text("Pause")').first
                if await pause_option.count() > 0:
                    await pause_option.click()
                    await page.wait_for_timeout(1500)
                    paused_count += 1
                    logger.info(f"  Paused campaign: {row_text[:50]}")
                else:
                    # No pause option — might already be paused, or might say "Resume"
                    resume_option = page.locator('li:has-text("Resume"), li:has-text("Activate"), button:has-text("Resume"), button:has-text("Activate")').first
                    if await resume_option.count() > 0:
                        # Already paused — close the menu
                        await page.keyboard.press("Escape")
                        already_paused += 1
                    else:
                        await page.keyboard.press("Escape")
                        logger.warning(f"  No pause/resume option for row {i}")
            else:
                # Try clicking the status dot directly to toggle
                if await status_dot.count() > 0:
                    await status_dot.click()
                    await page.wait_for_timeout(1500)
                    paused_count += 1

        total = paused_count + already_paused
        logger.info(f"InsuranceAgents.ai: {paused_count} paused, {already_paused} already paused")
        return {
            "success": True,
            "action": "paused",
            "paused": paused_count,
            "already_paused": already_paused,
            "total_campaigns": count,
        }

    except Exception as e:
        logger.error(f"InsuranceAgents.ai pause error: {e}")
        return {"success": False, "error": str(e)}


async def unpause(page: Page, email: str, password: str) -> dict:
    """Activate all campaigns on InsuranceAgents.ai."""
    try:
        if not await login(page, email, password):
            return {"success": False, "error": "Login failed"}

        rows, count = await _get_campaign_rows(page)
        if count == 0:
            return {"success": False, "error": "No campaigns found"}

        activated_count = 0
        already_active = 0

        for i in range(count):
            row = rows.nth(i)
            row_text = await row.inner_text()

            options_btn = row.locator('button:has-text("..."), [class*="options"], [class*="menu"], [aria-label*="option" i], td:last-child button').first

            if await options_btn.count() > 0:
                await options_btn.click()
                await page.wait_for_timeout(1000)

                # Look for Resume/Activate option
                resume_option = page.locator('li:has-text("Resume"), li:has-text("Activate"), button:has-text("Resume"), button:has-text("Activate"), [role="menuitem"]:has-text("Resume"), [role="menuitem"]:has-text("Activate")').first
                if await resume_option.count() > 0:
                    await resume_option.click()
                    await page.wait_for_timeout(1500)
                    activated_count += 1
                    logger.info(f"  Activated campaign: {row_text[:50]}")
                else:
                    # No resume option — might already be active
                    pause_option = page.locator('li:has-text("Pause"), button:has-text("Pause")').first
                    if await pause_option.count() > 0:
                        await page.keyboard.press("Escape")
                        already_active += 1
                    else:
                        await page.keyboard.press("Escape")
            else:
                status_dot = row.locator('[class*="status"], [class*="dot"], [class*="circle"]').first
                if await status_dot.count() > 0:
                    await status_dot.click()
                    await page.wait_for_timeout(1500)
                    activated_count += 1

        logger.info(f"InsuranceAgents.ai: {activated_count} activated, {already_active} already active")
        return {
            "success": True,
            "action": "resumed",
            "activated": activated_count,
            "already_active": already_active,
            "total_campaigns": count,
        }

    except Exception as e:
        logger.error(f"InsuranceAgents.ai unpause error: {e}")
        return {"success": False, "error": str(e)}
