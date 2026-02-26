"""
All Web Leads - Playwright automation driver.
Target: CALLS only (not Leads).

DOM: div.pause-inner-container.calls contains:
  button.pause-button[data-type="Call"]  (visible when active)
  button.resume-button[data-type="Call"] (visible when paused, hidden when active)

Pause flow: click Pause -> modal opens with "Resume Date" + time dropdown -> click "Pause Calls"
Resume flow: click Resume button (no modal)
"""
import logging
from datetime import datetime, timedelta
from playwright.async_api import Page

logger = logging.getLogger("lead-pauser.awl")

LOGIN_URL = "https://secure.allwebleads.com/login?returnUrl=%2f"
PAUSE_URL = "https://secure.allwebleads.com/Leads/Pause"


async def login(page: Page, username: str, password: str) -> bool:
    try:
        await page.goto(LOGIN_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        username_input = page.locator('input[name="Username"]').first
        if await username_input.count() == 0:
            username_input = page.locator('input[type="text"]').first
        await username_input.fill(username)

        password_input = page.locator('input[name="Password"]').first
        if await password_input.count() == 0:
            password_input = page.locator('input[type="password"]').first
        await password_input.fill(password)

        login_btn = page.locator('input[value="Log In"]').first
        if await login_btn.count() == 0:
            login_btn = page.locator('button:has-text("Log In")').first
        if await login_btn.count() == 0:
            login_btn = page.locator('input[type="submit"]').first
        await login_btn.click()

        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

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
    """Pause CALLS on AWL."""
    try:
        if not await login(page, username, password):
            return {"success": False, "error": "Login failed"}

        await page.goto(PAUSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Check if already paused
        is_hidden = await page.evaluate("""() => {
            const container = document.querySelector('.pause-inner-container.calls');
            if (!container) return 'no_container';
            const pauseBtn = container.querySelector('.pause-button');
            if (!pauseBtn) return 'no_button';
            return pauseBtn.classList.contains('hidden') ? 'hidden' : 'visible';
        }""")

        if is_hidden == 'hidden':
            logger.info("AWL: Calls already paused")
            return {"success": True, "action": "already_paused"}

        if is_hidden != 'visible':
            return {"success": False, "error": f"Unexpected state: {is_hidden}"}

        # Click the Pause button via JS
        await page.evaluate("""() => {
            document.querySelector('.pause-inner-container.calls .pause-button').click();
        }""")
        await page.wait_for_timeout(2000)

        # Modal opens with a datepicker calendar. Click the date input to open calendar.
        date_input = page.locator('input[placeholder="Resume Date"], input:visible').first
        await date_input.click()
        await page.wait_for_timeout(1000)

        # Calendar is showing. Click tomorrow's date or the next available date.
        # Strategy: click the ">" arrow to go to next month, then click day "1"
        # OR just click the last day visible in the current month (27 or 28)
        
        # Simpler: just click tomorrow or any future date that's visible and clickable
        clicked_date = await page.evaluate("""() => {
            // Find all clickable day cells in the calendar
            const cells = document.querySelectorAll('td, .day, [class*="day"], .datepicker td');
            const today = new Date().getDate();
            
            // Look for tomorrow or any day after today
            for (const cell of cells) {
                const text = cell.textContent.trim();
                const num = parseInt(text);
                if (num > today && num <= 31 && cell.offsetParent !== null && 
                    !cell.classList.contains('disabled') && !cell.classList.contains('off')) {
                    cell.click();
                    return num;
                }
            }
            
            // If we're at end of month, click the ">" arrow to go to next month
            const nextArrow = document.querySelector('.next, .datepicker-next, [class*="next"], button:has-text(">")');
            if (nextArrow) {
                nextArrow.click();
                return 'next_month';
            }
            
            return null;
        }""")
        
        logger.info(f"AWL: Clicked date: {clicked_date}")
        
        if clicked_date == 'next_month':
            await page.wait_for_timeout(500)
            # Now click day 1 of next month
            await page.evaluate("""() => {
                const cells = document.querySelectorAll('td, .day, [class*="day"]');
                for (const cell of cells) {
                    if (cell.textContent.trim() === '1' && cell.offsetParent !== null &&
                        !cell.classList.contains('disabled') && !cell.classList.contains('off')) {
                        cell.click();
                        return true;
                    }
                }
                return false;
            }""")
        
        await page.wait_for_timeout(1000)

        # Click "Pause Calls" confirmation button
        pause_confirm = page.locator('button:has-text("Pause Calls")').first
        if await pause_confirm.count() > 0:
            await pause_confirm.click()
            await page.wait_for_timeout(3000)
            logger.info("AWL: Clicked 'Pause Calls' confirmation")
            return {"success": True, "action": "paused"}

        # JS fallback
        clicked = await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.includes('Pause Calls') && btn.offsetParent !== null) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")
        if clicked:
            await page.wait_for_timeout(3000)
            logger.info("AWL: Paused via JS 'Pause Calls' button")
            return {"success": True, "action": "paused"}

        return {"success": False, "error": "Could not confirm pause in modal"}

    except Exception as e:
        logger.error(f"AWL pause error: {e}")
        return {"success": False, "error": str(e)}


async def unpause(page: Page, username: str, password: str) -> dict:
    """Resume CALLS on AWL."""
    try:
        if not await login(page, username, password):
            return {"success": False, "error": "Login failed"}

        await page.goto(PAUSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Check if already active
        is_hidden = await page.evaluate("""() => {
            const container = document.querySelector('.pause-inner-container.calls');
            if (!container) return 'no_container';
            const resumeBtn = container.querySelector('.resume-button');
            if (!resumeBtn) return 'no_button';
            return resumeBtn.classList.contains('hidden') ? 'hidden' : 'visible';
        }""")

        if is_hidden == 'hidden':
            logger.info("AWL: Calls already active")
            return {"success": True, "action": "already_active"}

        if is_hidden != 'visible':
            return {"success": False, "error": f"Unexpected state: {is_hidden}"}

        # Click Resume button via JS (no modal needed for resume)
        await page.evaluate("""() => {
            document.querySelector('.pause-inner-container.calls .resume-button').click();
        }""")
        await page.wait_for_timeout(3000)

        logger.info("AWL: Calls resumed")
        return {"success": True, "action": "resumed"}

    except Exception as e:
        logger.error(f"AWL unpause error: {e}")
        return {"success": False, "error": str(e)}
