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
        errors = 0

        for i in range(count):
            row = rows.nth(i)
            try:
                row_text = (await row.inner_text()).strip()[:60]

                # Find the "..." button — it's typically a small button with three dots
                # Avoid matching hidden dropdown-menu divs by checking visibility
                options_btn = None
                for selector in [
                    'button:has-text("⋮")',
                    'button:has-text("...")',
                    'button:has-text("⋯")',
                    '[class*="dropdown-toggle"]',
                    'button[data-toggle="dropdown"]',
                    'a[data-toggle="dropdown"]',
                ]:
                    el = row.locator(selector).first
                    if await el.count() > 0 and await el.is_visible():
                        options_btn = el
                        break

                if not options_btn:
                    # Try the last visible button in the row
                    all_btns = row.locator('button:visible, a.btn:visible')
                    btn_count = await all_btns.count()
                    if btn_count > 0:
                        options_btn = all_btns.nth(btn_count - 1)

                if options_btn and await options_btn.is_visible():
                    await options_btn.click()
                    await page.wait_for_timeout(1500)

                    # Look for Pause option in the now-visible dropdown
                    pause_option = page.locator('[role="menuitem"]:has-text("Pause"):visible, li:has-text("Pause"):visible, a:has-text("Pause"):visible, button:has-text("Pause"):visible').first
                    if await pause_option.count() > 0:
                        await pause_option.click()
                        await page.wait_for_timeout(2000)
                        paused_count += 1
                        logger.info(f"  Paused: {row_text}")
                    else:
                        # Check if Resume/Activate is showing (meaning already paused)
                        resume_opt = page.locator('[role="menuitem"]:has-text("Resume"):visible, [role="menuitem"]:has-text("Activate"):visible, li:has-text("Resume"):visible, li:has-text("Activate"):visible').first
                        if await resume_opt.count() > 0:
                            await page.keyboard.press("Escape")
                            already_paused += 1
                        else:
                            await page.keyboard.press("Escape")
                            errors += 1
                else:
                    logger.warning(f"  No visible options button for row {i}")
                    errors += 1

            except Exception as row_err:
                logger.warning(f"  Error on row {i}: {row_err}")
                await page.keyboard.press("Escape")
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
    """Activate all campaigns on InsuranceAgents.ai."""
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

                options_btn = None
                for selector in [
                    'button:has-text("⋮")',
                    'button:has-text("...")',
                    'button:has-text("⋯")',
                    '[class*="dropdown-toggle"]',
                    'button[data-toggle="dropdown"]',
                    'a[data-toggle="dropdown"]',
                ]:
                    el = row.locator(selector).first
                    if await el.count() > 0 and await el.is_visible():
                        options_btn = el
                        break

                if not options_btn:
                    all_btns = row.locator('button:visible, a.btn:visible')
                    btn_count = await all_btns.count()
                    if btn_count > 0:
                        options_btn = all_btns.nth(btn_count - 1)

                if options_btn and await options_btn.is_visible():
                    await options_btn.click()
                    await page.wait_for_timeout(1500)

                    resume_opt = page.locator('[role="menuitem"]:has-text("Resume"):visible, [role="menuitem"]:has-text("Activate"):visible, li:has-text("Resume"):visible, li:has-text("Activate"):visible, a:has-text("Resume"):visible, a:has-text("Activate"):visible').first
                    if await resume_opt.count() > 0:
                        await resume_opt.click()
                        await page.wait_for_timeout(2000)
                        activated_count += 1
                        logger.info(f"  Activated: {row_text}")
                    else:
                        pause_opt = page.locator('[role="menuitem"]:has-text("Pause"):visible, li:has-text("Pause"):visible').first
                        if await pause_opt.count() > 0:
                            await page.keyboard.press("Escape")
                            already_active += 1
                        else:
                            await page.keyboard.press("Escape")
                            errors += 1
                else:
                    errors += 1

            except Exception as row_err:
                logger.warning(f"  Error on row {i}: {row_err}")
                await page.keyboard.press("Escape")
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
