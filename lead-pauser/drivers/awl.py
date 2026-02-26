"""
All Web Leads - Playwright automation driver.
Target: CALLS only (not Leads).

Page layout (secure.allwebleads.com/Leads/Pause):
  "Leads are active"    [Pause button]
  "Calls are paused"    [Update button] [Resume button]
  - or -
  "Calls are active"    [Pause button]

Each row is a separate section. Buttons have text like "Resume" and "Pause".
"""
import logging
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


async def _click_calls_button(page: Page, button_text: str) -> str:
    """Find the Calls section and click Pause or Resume. Pure JS approach."""
    result = await page.evaluate("""(buttonText) => {
        const body = document.body.innerText;
        const callsPaused = body.includes('Calls are paused');
        const callsActive = body.includes('Calls are active');

        if (buttonText === 'Pause' && callsPaused) return 'already_paused';
        if (buttonText === 'Resume' && callsActive) return 'already_active';

        // Find all buttons containing target text
        const allButtons = Array.from(document.querySelectorAll('button, input[type="button"], a.btn'));
        const targetButtons = allButtons.filter(btn => btn.textContent.includes(buttonText));

        if (targetButtons.length === 0) return 'no_button_found';

        if (buttonText === 'Pause') {
            // Page has 2 rows: Leads then Calls. 2 Pause buttons = [0]=Leads, [1]=Calls
            if (targetButtons.length >= 2) {
                targetButtons[1].click();
                return 'clicked_calls_pause';
            }
            // Only 1 pause button - Leads might already be paused, this is for Calls
            targetButtons[0].click();
            return 'clicked_only_pause';
        }

        if (buttonText === 'Resume') {
            // Find Resume button in the Calls row (parent contains "Calls")
            for (const btn of targetButtons) {
                let el = btn.parentElement;
                for (let i = 0; i < 8; i++) {
                    if (el && el.textContent && el.textContent.includes('Calls')) {
                        btn.click();
                        return 'clicked_calls_resume';
                    }
                    if (el) el = el.parentElement;
                }
            }
            // Fallback: Calls row is below Leads, so last Resume button
            targetButtons[targetButtons.length - 1].click();
            return 'clicked_last_resume';
        }

        return 'no_match';
    }""", button_text)
    return result


async def pause(page: Page, username: str, password: str) -> dict:
    try:
        if not await login(page, username, password):
            return {"success": False, "error": "Login failed"}

        await page.goto(PAUSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        result = await _click_calls_button(page, "Pause")
        logger.info(f"AWL: Pause result: {result}")

        if result == "already_paused":
            return {"success": True, "action": "already_paused"}
        elif result and "clicked" in result:
            await page.wait_for_timeout(3000)
            return {"success": True, "action": "paused"}
        else:
            return {"success": False, "error": f"Could not pause: {result}"}
    except Exception as e:
        logger.error(f"AWL pause error: {e}")
        return {"success": False, "error": str(e)}


async def unpause(page: Page, username: str, password: str) -> dict:
    try:
        if not await login(page, username, password):
            return {"success": False, "error": "Login failed"}

        await page.goto(PAUSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        result = await _click_calls_button(page, "Resume")
        logger.info(f"AWL: Resume result: {result}")

        if result == "already_active":
            return {"success": True, "action": "already_active"}
        elif result and "clicked" in result:
            await page.wait_for_timeout(3000)
            return {"success": True, "action": "resumed"}
        else:
            return {"success": False, "error": f"Could not resume: {result}"}
    except Exception as e:
        logger.error(f"AWL unpause error: {e}")
        return {"success": False, "error": str(e)}
