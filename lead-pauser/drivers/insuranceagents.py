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
        await page.goto(LOGIN_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        email_input = page.locator('input[type="email"]').first
        if await email_input.count() == 0:
            email_input = page.locator('input[name="email"], input[placeholder*="mail" i]').first
        if await email_input.count() == 0:
            email_input = page.locator('input[type="text"]').first
        await email_input.fill(email)

        password_input = page.locator('input[type="password"]').first
        if await password_input.count() == 0:
            password_input = page.locator('input[name="password"]').first
        await password_input.fill(password)

        login_btn = page.locator('button:has-text("Log In"), button:has-text("Login")').first
        if await login_btn.count() == 0:
            login_btn = page.locator('button[type="submit"]').first
        await login_btn.click()

        await page.wait_for_timeout(5000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

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
    await page.goto(CAMPAIGNS_URL, timeout=60000)
    await page.wait_for_load_state("domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    rows = page.locator('#campaigns-table tbody tr, table tbody tr')
    count = await rows.count()
    logger.info(f"InsuranceAgents.ai: Found {count} campaign rows")
    return rows, count


async def pause(page: Page, email: str, password: str) -> dict:
    """Pause all campaigns on InsuranceAgents.ai by clicking status dots."""
    try:
        if not await login(page, email, password):
            return {"success": False, "error": "Login failed"}

        rows, count = await _get_campaign_rows(page)
        if count == 0:
            return {"success": False, "error": "No campaigns found"}

        paused_count = 0
        already_paused = 0
        errors = 0

        for i in range(count):
            row = rows.nth(i)
            try:
                row_text = (await row.inner_text()).strip()[:60]

                # Find the status dot — it's an <i> with class "mil-circle" and color class
                # Green = sfgreen (active), Red = sfred (paused)
                status_dot = row.locator('i.mil-circle, [class*="mil-circle"]').first

                if await status_dot.count() > 0:
                    # Check if already paused (has sfred class)
                    dot_class = await status_dot.get_attribute("class") or ""
                    if "sfred" in dot_class:
                        already_paused += 1
                        continue

                    # Click the green dot to open dropdown
                    await status_dot.click()
                    await page.wait_for_timeout(1000)

                    # Click "Paused" option in the dropdown
                    paused_option = page.locator('li:has-text("Paused"):visible, a:has-text("Paused"):visible').first
                    if await paused_option.count() > 0:
                        await paused_option.click()
                        await page.wait_for_timeout(1500)
                        paused_count += 1
                        logger.info(f"  Paused: {row_text}")
                    else:
                        await page.keyboard.press("Escape")
                        errors += 1
                else:
                    errors += 1

            except Exception as row_err:
                logger.warning(f"  Error on row {i}: {row_err}")
                try:
                    await page.keyboard.press("Escape")
                except:
                    pass
                errors += 1

        logger.info(f"InsuranceAgents.ai: {paused_count} paused, {already_paused} already paused, {errors} errors")
        return {
            "success": paused_count > 0 or already_paused > 0,
            "action": "paused",
            "paused": paused_count,
            "already_paused": already_paused,
            "errors": errors,
            "total_campaigns": count,
        }

    except Exception as e:
        logger.error(f"InsuranceAgents.ai pause error: {e}")
        return {"success": False, "error": str(e)}


async def unpause(page: Page, email: str, password: str) -> dict:
    """Activate all campaigns on InsuranceAgents.ai by clicking status dots."""
    try:
        if not await login(page, email, password):
            return {"success": False, "error": "Login failed"}

        rows, count = await _get_campaign_rows(page)
        if count == 0:
            return {"success": False, "error": "No campaigns found"}

        activated_count = 0
        already_active = 0
        errors = 0

        for i in range(count):
            row = rows.nth(i)
            try:
                row_text = (await row.inner_text()).strip()[:60]

                # Find the status dot
                status_dot = row.locator('i.mil-circle, [class*="mil-circle"]').first

                if await status_dot.count() > 0:
                    dot_class = await status_dot.get_attribute("class") or ""
                    if "sfgreen" in dot_class:
                        already_active += 1
                        continue

                    # Click the red dot to open dropdown
                    await status_dot.click()
                    await page.wait_for_timeout(1000)

                    # Click "Active" option in the dropdown
                    active_option = page.locator('li:has-text("Active"):visible, a:has-text("Active"):visible').first
                    if await active_option.count() > 0:
                        await active_option.click()
                        await page.wait_for_timeout(1500)
                        activated_count += 1
                        logger.info(f"  Activated: {row_text}")
                    else:
                        await page.keyboard.press("Escape")
                        errors += 1
                else:
                    errors += 1

            except Exception as row_err:
                logger.warning(f"  Error on row {i}: {row_err}")
                try:
                    await page.keyboard.press("Escape")
                except:
                    pass
                errors += 1

        logger.info(f"InsuranceAgents.ai: {activated_count} activated, {already_active} already active, {errors} errors")
        return {
            "success": activated_count > 0 or already_active > 0,
            "action": "resumed",
            "activated": activated_count,
            "already_active": already_active,
            "errors": errors,
            "total_campaigns": count,
        }

    except Exception as e:
        logger.error(f"InsuranceAgents.ai unpause error: {e}")
        return {"success": False, "error": str(e)}
