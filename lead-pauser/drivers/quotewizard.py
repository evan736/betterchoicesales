"""
QuoteWizard — Playwright automation driver.

Pause flow:
  1. Login at Azure B2C form (email + password → Sign in)
  2. Navigate to Pause tab (admin.quotewizard.com → Account → Pause)
  3. Click "Add Pause" button → set From=now, To=tomorrow 9am → confirm

Unpause flow:
  1. Login (same)
  2. Navigate to Pause tab
  3. Click "End Pause Now" button
"""
import logging
from datetime import datetime, timedelta
from playwright.async_api import Page

logger = logging.getLogger("lead-pauser.quotewizard")

LOGIN_URL = "https://admin.quotewizard.com"
PAUSE_TAB_SELECTOR = 'a:has-text("Pause"), [href*="pause" i]'


async def login(page: Page, email: str, password: str) -> bool:
    """Login to QuoteWizard via Azure B2C."""
    try:
        await page.goto(LOGIN_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Azure B2C login form
        email_input = page.locator('input[type="email"]').first
        if await email_input.count() == 0:
            email_input = page.locator('input[id*="email" i], input[name*="email" i]').first
        if await email_input.count() == 0:
            email_input = page.locator('input[type="text"]').first
        await email_input.fill(email)

        password_input = page.locator('input[type="password"]').first
        await password_input.fill(password)

        submit = page.locator('button[type="submit"]').first
        if await submit.count() == 0:
            submit = page.locator('button:has-text("Sign in"), input[type="submit"]').first
        await submit.click()

        # Wait for redirect — B2C can be slow
        await page.wait_for_timeout(5000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        url = page.url.lower()
        if "b2clogin" not in url and "authorize" not in url:
            logger.info("QuoteWizard: Login successful")
            return True

        # Extra wait for slow redirects
        await page.wait_for_timeout(8000)
        url = page.url.lower()
        if "b2clogin" not in url and "authorize" not in url:
            logger.info("QuoteWizard: Login successful (after redirect)")
            return True

        logger.error(f"QuoteWizard: Login may have failed, on {page.url}")
        return False

    except Exception as e:
        logger.error(f"QuoteWizard: Login failed: {e}")
        return False


async def _navigate_to_pause_tab(page: Page) -> bool:
    """Navigate to the Pause tab from dashboard."""
    try:
        # Step 1: Extract client ID from current URL or page content
        current_url = page.url
        client_id = None
        
        # Check if we're already on a client page
        if "/client/" in current_url:
            # Extract client ID: /client/{uuid}/...
            parts = current_url.split("/client/")
            if len(parts) > 1:
                client_id = parts[1].split("/")[0]
        
        # Step 2: If we have a client ID, navigate directly to pause tab
        if client_id:
            pause_url = f"https://admin.quotewizard.com/client/{client_id}/pause"
            logger.info(f"QuoteWizard: Navigating to {pause_url}")
            await page.goto(pause_url, timeout=30000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            
            content = await page.content()
            if "404" not in page.url and ("Pause" in content or "pause" in content.lower()):
                logger.info("QuoteWizard: Navigated to Pause tab via direct URL")
                return True

        # Step 3: Try to find the account page link first to get client ID
        # Look for any link containing /client/ in the page
        account_link = await page.evaluate("""() => {
            const links = document.querySelectorAll('a[href*="/client/"]');
            for (const link of links) {
                return link.href;
            }
            return null;
        }""")
        
        if account_link and "/client/" in account_link:
            parts = account_link.split("/client/")
            if len(parts) > 1:
                client_id = parts[1].split("/")[0]
                pause_url = f"https://admin.quotewizard.com/client/{client_id}/pause"
                await page.goto(pause_url, timeout=30000)
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
                
                if "404" not in page.url:
                    logger.info("QuoteWizard: Found client ID from page links")
                    return True

        # Step 4: Navigate to account page first, then click Pause tab
        if client_id:
            account_url = f"https://admin.quotewizard.com/client/{client_id}/account"
            await page.goto(account_url, timeout=30000)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            
            pause_link = page.locator('a:text-is("Pause")').first
            if await pause_link.count() > 0 and await pause_link.is_visible():
                await pause_link.click()
                await page.wait_for_timeout(3000)
                logger.info("QuoteWizard: Clicked Pause tab from account page")
                return True

        # Step 5: Try known client ID as hardcoded fallback
        known_id = "e95fa754-5cc3-4f8c-b8bc-248347b81ba2"
        pause_url = f"https://admin.quotewizard.com/client/{known_id}/pause"
        await page.goto(pause_url, timeout=30000)
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        if "404" not in page.url:
            logger.info("QuoteWizard: Used known client ID fallback")
            return True

        logger.error(f"QuoteWizard: Could not find Pause tab. URL: {page.url}")
        return False

    except Exception as e:
        logger.error(f"QuoteWizard: Navigate to pause tab failed: {e}")
        return False


async def pause(page: Page, email: str, password: str) -> dict:
    """Pause account on QuoteWizard."""
    try:
        if not await login(page, email, password):
            return {"success": False, "error": "Login failed"}

        if not await _navigate_to_pause_tab(page):
            return {"success": False, "error": "Could not find Pause tab"}

        content = await page.content()

        # Check if already paused
        if "Paused - Vacation" in content or "End Pause Now" in content:
            logger.info("QuoteWizard: Already paused")
            return {"success": True, "action": "already_paused"}

        # Click "Add Pause" button
        add_pause = page.locator('button:has-text("Add Pause"), a:has-text("Add Pause")').first
        if await add_pause.count() > 0:
            await add_pause.click()
            await page.wait_for_timeout(3000)

            # Modal should appear with "Create a Pause" and a Save button
            # Wait for Save button to be visible
            save_btn = page.locator('button:has-text("Save"):visible').first
            if await save_btn.count() > 0:
                await save_btn.click()
                await page.wait_for_timeout(5000)
                logger.info("QuoteWizard: Clicked Save — paused successfully")
                return {"success": True, "action": "paused"}

            # Try other confirm buttons
            for selector in [
                'button:has-text("Confirm"):visible',
                'button:has-text("Submit"):visible',
                'button[type="submit"]:visible',
                'button.btn-primary:visible',
            ]:
                btn = page.locator(selector).first
                if await btn.count() > 0:
                    await btn.click()
                    await page.wait_for_timeout(5000)
                    logger.info(f"QuoteWizard: Clicked {selector} — paused")
                    return {"success": True, "action": "paused"}

            # JS fallback — find and click any Save button in the modal
            clicked = await page.evaluate("""() => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    if (btn.textContent.trim() === 'Save' && btn.offsetParent !== null) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }""")
            if clicked:
                await page.wait_for_timeout(5000)
                logger.info("QuoteWizard: Clicked Save via JS")
                return {"success": True, "action": "paused"}

            return {"success": False, "error": "Save button not found in modal"}
        else:
            return {"success": False, "error": "Add Pause button not found"}

    except Exception as e:
        logger.error(f"QuoteWizard pause error: {e}")
        return {"success": False, "error": str(e)}


async def unpause(page: Page, email: str, password: str) -> dict:
    """End pause on QuoteWizard."""
    try:
        if not await login(page, email, password):
            return {"success": False, "error": "Login failed"}

        if not await _navigate_to_pause_tab(page):
            return {"success": False, "error": "Could not find Pause tab"}

        content = await page.content()

        if "End Pause Now" in content:
            end_btn = page.locator('button:has-text("End Pause Now"), a:has-text("End Pause Now")').first
            if await end_btn.count() > 0:
                await end_btn.click()
                await page.wait_for_load_state("networkidle", timeout=10000)
                await page.wait_for_timeout(2000)
                logger.info("QuoteWizard: Unpaused successfully")
                return {"success": True, "action": "resumed"}
            return {"success": False, "error": "End Pause Now button not clickable"}

        elif "Paused" not in content:
            logger.info("QuoteWizard: Already active")
            return {"success": True, "action": "already_active"}
        else:
            return {"success": False, "error": "Unknown pause state"}

    except Exception as e:
        logger.error(f"QuoteWizard unpause error: {e}")
        return {"success": False, "error": str(e)}
