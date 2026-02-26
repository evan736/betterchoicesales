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

        # Calendar is showing. Click tomorrow (27) or day after (28).
        # Use Playwright to click the visible "27" text on the calendar
        day_clicked = False
        for day_num in ["27", "28", "1"]:
            day_cell = page.locator(f'td:text-is("{day_num}")').first
            if await day_cell.count() > 0 and await day_cell.is_visible():
                await day_cell.click()
                await page.wait_for_timeout(1000)
                logger.info(f"AWL: Clicked day {day_num} on calendar")
                day_clicked = True
                break

        if not day_clicked:
            # Click the ">" next month arrow, then click day "1"
            next_arrow = page.locator('text=">"').first
            if await next_arrow.count() == 0:
                next_arrow = page.locator('[class*="next"], .fa-chevron-right, .glyphicon-chevron-right').first
            if await next_arrow.count() > 0:
                await next_arrow.click()
                await page.wait_for_timeout(500)
                day_one = page.locator('td:text-is("1")').first
                if await day_one.count() > 0:
                    await day_one.click()
                    await page.wait_for_timeout(1000)
                    logger.info("AWL: Clicked day 1 of next month")
                    day_clicked = True

        if not day_clicked:
            # Last resort: JS click any td with a number > today
            await page.evaluate("""() => {
                const tds = document.querySelectorAll('td');
                for (const td of tds) {
                    const num = parseInt(td.textContent.trim());
                    if (num === 27 || num === 28) {
                        td.click();
                        return true;
                    }
                }
                return false;
            }""")
            logger.info("AWL: Clicked date via JS fallback")
        
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
