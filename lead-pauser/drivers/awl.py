"""
All Web Leads - Playwright automation driver.
Target: CALLS only (not Leads).

DOM structure:
  div.pause-inner-container.calls
    button.pause-button[data-type="Call"]   (visible when active, hidden when paused)
    button.resume-button[data-type="Call"]  (visible when paused, hidden when active)
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


async def pause(page: Page, username: str, password: str) -> dict:
    """Pause CALLS on AWL. Click the pause-button inside .pause-inner-container.calls"""
    try:
        if not await login(page, username, password):
            return {"success": False, "error": "Login failed"}

        await page.goto(PAUSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Use JS to click the exact button: .pause-inner-container.calls .pause-button
        result = await page.evaluate("""() => {
            const container = document.querySelector('.pause-inner-container.calls');
            if (!container) return 'no_calls_container';

            const pauseBtn = container.querySelector('.pause-button');
            const resumeBtn = container.querySelector('.resume-button');

            // If pause button is hidden, calls are already paused
            if (pauseBtn && pauseBtn.classList.contains('hidden')) return 'already_paused';

            // If pause button exists and is not hidden, click it
            if (pauseBtn && !pauseBtn.classList.contains('hidden')) {
                pauseBtn.click();
                return 'clicked';
            }

            return 'button_not_found';
        }""")

        logger.info(f"AWL: Pause calls result: {result}")

        if result == "already_paused":
            return {"success": True, "action": "already_paused"}
        elif result == "clicked":
            await page.wait_for_timeout(3000)
            return {"success": True, "action": "paused"}
        else:
            return {"success": False, "error": result}

    except Exception as e:
        logger.error(f"AWL pause error: {e}")
        return {"success": False, "error": str(e)}


async def unpause(page: Page, username: str, password: str) -> dict:
    """Resume CALLS on AWL. Click the resume-button inside .pause-inner-container.calls"""
    try:
        if not await login(page, username, password):
            return {"success": False, "error": "Login failed"}

        await page.goto(PAUSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        result = await page.evaluate("""() => {
            const container = document.querySelector('.pause-inner-container.calls');
            if (!container) return 'no_calls_container';

            const resumeBtn = container.querySelector('.resume-button');
            const pauseBtn = container.querySelector('.pause-button');

            // If resume button is hidden, calls are already active
            if (resumeBtn && resumeBtn.classList.contains('hidden')) return 'already_active';

            // If resume button exists and is not hidden, click it
            if (resumeBtn && !resumeBtn.classList.contains('hidden')) {
                resumeBtn.click();
                return 'clicked';
            }

            return 'button_not_found';
        }""")

        logger.info(f"AWL: Resume calls result: {result}")

        if result == "already_active":
            return {"success": True, "action": "already_active"}
        elif result == "clicked":
            await page.wait_for_timeout(3000)
            return {"success": True, "action": "resumed"}
        else:
            return {"success": False, "error": result}

    except Exception as e:
        logger.error(f"AWL unpause error: {e}")
        return {"success": False, "error": str(e)}
