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
    """Pause CALLS on All Web Leads (not leads)."""
    try:
        if not await login(page, username, password):
            return {"success": False, "error": "Login failed"}

        await page.goto(PAUSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        content = await page.content()

        # Check if calls are already paused
        if "Calls are paused" in content or "calls are paused" in content.lower():
            logger.info("AWL: Calls already paused")
            return {"success": True, "action": "already_paused"}

        # Target the Call pause button specifically (data-type="Call")
        call_pause_btn = page.locator('button[data-type="Call"].pause-button:visible').first
        if await call_pause_btn.count() > 0:
            await call_pause_btn.click()
            await page.wait_for_timeout(3000)
            logger.info("AWL: Calls paused via data-type=Call button")
            return {"success": True, "action": "paused"}

        # Fallback: use JavaScript to find the Call pause button
        clicked = await page.evaluate("""() => {
            // Look for pause button with data-type="Call"
            const btn = document.querySelector('button.pause-button[data-type="Call"]');
            if (btn && !btn.classList.contains('hidden')) {
                btn.click();
                return 'call_button';
            }
            // Try unhiding it
            if (btn) {
                btn.classList.remove('hidden');
                btn.click();
                return 'call_button_unhidden';
            }
            // Look in the Calls section
            const sections = document.querySelectorAll('.pause-section, .card, [class*="section"]');
            for (const sec of sections) {
                if (sec.textContent.includes('Call')) {
                    const pauseBtn = sec.querySelector('.pause-button, button:not(.resume-button)');
                    if (pauseBtn) {
                        pauseBtn.click();
                        return 'section_button';
                    }
                }
            }
            return null;
        }""")
        if clicked:
            await page.wait_for_timeout(3000)
            logger.info(f"AWL: Calls paused via JS ({clicked})")
            return {"success": True, "action": "paused"}

        # Last fallback: click any visible pause button
        pause_btn = page.locator('button.pause-button:visible').first
        if await pause_btn.count() > 0:
            await pause_btn.click()
            await page.wait_for_timeout(3000)
            logger.info("AWL: Paused via generic visible button")
            return {"success": True, "action": "paused"}

        return {"success": False, "error": "Call pause button not found"}

    except Exception as e:
        logger.error(f"AWL pause error: {e}")
        return {"success": False, "error": str(e)}


async def unpause(page: Page, username: str, password: str) -> dict:
    """Resume CALLS on All Web Leads (not leads)."""
    try:
        if not await login(page, username, password):
            return {"success": False, "error": "Login failed"}

        await page.goto(PAUSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        content = await page.content()

        # Check if calls are already active
        if "Calls are active" in content or ("active" in content.lower() and "call" in content.lower()):
            logger.info("AWL: Calls already active")
            return {"success": True, "action": "already_active"}

        # Target the Call resume button specifically (data-type="Call")
        call_resume_btn = page.locator('button[data-type="Call"].resume-button:visible').first
        if await call_resume_btn.count() > 0:
            await call_resume_btn.click()
            await page.wait_for_timeout(3000)
            logger.info("AWL: Calls resumed via data-type=Call button")
            return {"success": True, "action": "resumed"}

        # Fallback: use JavaScript to find the Call resume button
        clicked = await page.evaluate("""() => {
            // Look for resume button with data-type="Call"
            const btn = document.querySelector('button.resume-button[data-type="Call"]');
            if (btn && !btn.classList.contains('hidden')) {
                btn.click();
                return 'call_button';
            }
            // Try unhiding it
            if (btn) {
                btn.classList.remove('hidden');
                btn.click();
                return 'call_button_unhidden';
            }
            // Look in the Calls section
            const sections = document.querySelectorAll('.pause-section, .card, [class*="section"]');
            for (const sec of sections) {
                if (sec.textContent.includes('Call')) {
                    const resumeBtn = sec.querySelector('.resume-button');
                    if (resumeBtn) {
                        resumeBtn.classList.remove('hidden');
                        resumeBtn.click();
                        return 'section_button';
                    }
                }
            }
            return null;
        }""")
        if clicked:
            await page.wait_for_timeout(3000)
            logger.info(f"AWL: Calls resumed via JS ({clicked})")
            return {"success": True, "action": "resumed"}

        # Last fallback: any visible resume button
        resume_btn = page.locator('button.resume-button:visible').first
        if await resume_btn.count() > 0:
            await resume_btn.click()
            await page.wait_for_timeout(3000)
            logger.info("AWL: Resumed via generic visible button")
            return {"success": True, "action": "resumed"}

        return {"success": False, "error": "Call resume button not found"}

    except Exception as e:
        logger.error(f"AWL unpause error: {e}")
        return {"success": False, "error": str(e)}
