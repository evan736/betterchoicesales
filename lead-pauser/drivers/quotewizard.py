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
        # Step 1: Check if Pause tab is already visible on page
        pause_link = page.locator('a:text-is("Pause")').first
        if await pause_link.count() > 0 and await pause_link.is_visible():
            await pause_link.click()
            await page.wait_for_timeout(3000)
            logger.info("QuoteWizard: Found and clicked Pause tab directly")
            return True

        # Step 2: Click the user icon in the top-right nav
        # From the screenshot: it's a person/user icon in the navbar
        # Try clicking various user-related elements that are VISIBLE
        selectors_to_try = [
            'a[href*="profile" i]',
            'a[href*="account" i]',
            '.avatar:visible',
            'nav .dropdown-toggle:last-child',
            'header .dropdown-toggle:last-child',
            '[class*="nav"] [data-toggle="dropdown"]:last-child',
            'a:has(svg[class*="user" i]):visible',
            'button:has(svg[class*="user" i]):visible',
        ]
        
        for selector in selectors_to_try:
            el = page.locator(selector).first
            if await el.count() > 0 and await el.is_visible():
                await el.click()
                await page.wait_for_timeout(2000)
                logger.info(f"QuoteWizard: Clicked user element: {selector}")
                
                # Look for Profile / Account Info link in dropdown
                profile_link = page.locator('a:has-text("Profile"), a:has-text("Account Info"), a:has-text("Account")').first
                if await profile_link.count() > 0 and await profile_link.is_visible():
                    await profile_link.click()
                    await page.wait_for_timeout(3000)
                    
                    # Now find Pause tab
                    pause_link = page.locator('a:text-is("Pause")').first
                    if await pause_link.count() > 0 and await pause_link.is_visible():
                        await pause_link.click()
                        await page.wait_for_timeout(3000)
                        logger.info("QuoteWizard: Navigated via user menu → Pause tab")
                        return True

                # Maybe clicking the icon went directly to account page
                pause_link = page.locator('a:text-is("Pause")').first
                if await pause_link.count() > 0 and await pause_link.is_visible():
                    await pause_link.click()
                    await page.wait_for_timeout(3000)
                    return True

        # Step 3: Try using keyboard/URL navigation as last resort
        # QuoteWizard admin URL might support direct navigation
        current_url = page.url
        if "admin.quotewizard.com" in current_url:
            # Try common URL patterns
            for path in ["/account/pause", "/pause", "/profile/pause"]:
                try:
                    await page.goto(f"https://admin.quotewizard.com{path}", timeout=15000)
                    await page.wait_for_timeout(2000)
                    content = await page.content()
                    if "Pause My Account" in content or "Add Pause" in content or "End Pause" in content:
                        logger.info(f"QuoteWizard: Found Pause page at {path}")
                        return True
                except:
                    continue

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
            await page.wait_for_timeout(2000)

            # A form/modal should appear — look for date inputs or just submit
            # The pause typically sets From=now and To=next morning
            # Try to find and click confirm/save/submit
            confirm = page.locator('button:has-text("Save"), button:has-text("Confirm"), button:has-text("Submit"), button:has-text("Add"), button[type="submit"]').first
            if await confirm.count() > 0:
                await confirm.click()
                await page.wait_for_load_state("networkidle", timeout=10000)
                logger.info("QuoteWizard: Paused successfully")
                return {"success": True, "action": "paused"}

            # If no confirm button, the Add Pause button itself might have done it
            await page.wait_for_timeout(2000)
            new_content = await page.content()
            if "Paused" in new_content or "End Pause Now" in new_content:
                logger.info("QuoteWizard: Paused successfully (after Add Pause click)")
                return {"success": True, "action": "paused"}

            return {"success": False, "error": "Could not confirm pause"}
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
