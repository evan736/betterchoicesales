"""
ORBIT Quoting Bot — National General
Browser automation for auto-quoting Custom360 Package (Home + Auto).
Runs locally on agent's machine with visual browser.

Usage:
    python bot.py quote --manual           Manual quote entry
    python bot.py quote --lead-id 123      Quote from ORBIT lead
    python bot.py test-login               Test NatGen portal login
    python bot.py screenshot               Interactive screenshot mode
"""

import os, sys, json, asyncio
from datetime import datetime, date
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich.panel import Panel

load_dotenv()
console = Console()

NATGEN_URL = os.getenv("NATGEN_PORTAL_URL", "https://natgenagency.com")
NATGEN_USER = os.getenv("NATGEN_USERNAME", "")
NATGEN_PASS = os.getenv("NATGEN_PASSWORD", "")
ORBIT_API = os.getenv("ORBIT_API_URL", "https://better-choice-api.onrender.com")
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO = int(os.getenv("SLOW_MO", "300"))
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "./screenshots"))
SCREENSHOT_DIR.mkdir(exist_ok=True)


class QuoteData:
    def __init__(self):
        self.first_name = ""
        self.last_name = ""
        self.dob = ""
        self.gender = "Male"
        self.marital_status = "Single"
        self.occupation = "Other"
        self.phone = "8888888888"
        self.phone_type = "Cell"
        self.email = ""
        self.consent_calls_texts = "Yes"
        self.opt_in_emails = "No"
        self.address = ""
        self.address2 = ""
        self.city = ""
        self.state = "IL"
        self.zip_code = ""
        self.deed_correction = "No"
        self.at_residence_3_years = "No"
        self.different_mailing = "No"
        self.has_co_applicant = "No"
        self.effective_date = date.today().strftime("%m/%d/%Y")
        self.year_built = ""
        self.roof_year = ""
        self.sqft = ""
        self.construction_type = ""
        self.roof_type = ""
        self.stories = ""
        self.foundation = ""
        self.coverage_a = ""
        self.deductible = "1000"
        self.liability = "300000"
        self.drivers = []
        self.vehicles = []
        self.bodily_injury = "100/300"
        self.property_damage = "100000"
        self.comp_ded = "500"
        self.collision_ded = "500"
        self.quoted_premium_total = ""
        self.quote_number = ""
        self.screenshots = []

    def to_dict(self):
        return self.__dict__.copy()

    @classmethod
    def from_orbit_lead(cls, lead):
        q = cls()
        q.first_name = lead.get("first_name", "")
        q.last_name = lead.get("last_name", "")
        q.email = lead.get("email", "")
        q.phone = lead.get("phone", "") or "8888888888"
        q.dob = lead.get("dob", "")
        q.address = lead.get("address", "")
        q.city = lead.get("city", "")
        q.state = lead.get("state", "IL")
        q.zip_code = lead.get("zip_code", "")
        q.year_built = lead.get("home_year", "") or lead.get("year_built", "")
        q.roof_year = lead.get("roof_year", "")
        q.sqft = lead.get("sqft", "")
        q.effective_date = lead.get("effective_date", "") or date.today().strftime("%m/%d/%Y")
        if q.first_name:
            q.drivers = [{"first_name": q.first_name, "last_name": q.last_name, "dob": q.dob, "gender": q.gender, "marital_status": q.marital_status}]
        return q


class NatGenBot:
    def __init__(self):
        self.browser = self.page = None
        self.shot_count = 0

    async def start(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
        self.context = await self.browser.new_context(viewport={"width": 1280, "height": 900})
        self.page = await self.context.new_page()
        console.print("[green]✓[/] Browser launched")

    async def shot(self, name):
        self.shot_count += 1
        f = SCREENSHOT_DIR / f"{self.shot_count:02d}_{name}_{datetime.now():%H%M%S}.png"
        await self.page.screenshot(path=str(f), full_page=True)
        console.print(f"  📸 {f.name}")
        return str(f)

    # ═══ SCREEN 1: LOGIN (two-step) ═══
    async def login(self):
        console.print(Panel("Screen 1: Login", style="cyan"))
        if not NATGEN_USER or not NATGEN_PASS:
            console.print("[red]✗ Set NATGEN_USERNAME and NATGEN_PASSWORD in .env[/]")
            return False

        # Step 1a: User ID page at natgenagency.com
        await self.page.goto(f"{NATGEN_URL}/Login.aspx?Menu=Login")
        await self.page.wait_for_load_state("networkidle")
        await self.shot("login_userid")

        # USER ID input + SIGN IN
        await self.page.fill("input[name='UserName'], input#UserName, input[type='text']", NATGEN_USER)
        await self.page.click("text=SIGN IN")
        console.print(f"  User ID: {NATGEN_USER} → SIGN IN")

        # Step 1b: Password page (login.natgenagency.com redirect)
        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)
        await self.shot("login_password")

        await self.page.fill("input[type='password']", NATGEN_PASS)
        await self.page.click("text=SIGN IN")
        console.print("  Password entered → SIGN IN")

        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)
        await self.shot("dashboard")

        if "MainMenu" in self.page.url:
            console.print("[green]  ✓ Logged in — Agent Dashboard loaded[/]")
            return True
        console.print(f"  [yellow]Page: {self.page.url}[/]")
        return True

    # ═══ SCREEN 2: DASHBOARD → NEW QUOTE ═══
    # Left sidebar: "New Quote" section
    # Dropdown 1: State (IL, IN, MN, MO, ND, OH, OK, PA, TN, TX)
    # Dropdown 2: Product (after state selected)
    #   Options: -Select-, PPA Value, Commercial Auto, Motorcycle,
    #   ATV/Scooters/Golf Cart, RV/Motorhome/Trailer, Flood,
    #   Custom360 Auto, Custom360 Home, Custom360 Package, Marketplace Commercial
    # Button: "Begin"

    async def start_new_quote(self, data):
        console.print(Panel("Screen 2: Dashboard → New Quote", style="cyan"))
        p = self.page

        # State dropdown — it's in the "New Quote" sidebar section
        # The first dropdown under "New Quote" that shows "-Select-"
        state_dd = p.locator("#ContentPlaceHolder1_ddlStates, select[name*='ddlStates']")
        if await state_dd.count() == 0:
            # Fallback: find by the New Quote section
            state_dd = p.locator("select").filter(has_text="-Select-").first
        await state_dd.select_option(label=data.state)
        console.print(f"  State: {data.state}")
        await asyncio.sleep(1.5)

        # Product dropdown appears after state selection
        product_dd = p.locator("#ContentPlaceHolder1_ddlProducts, select[name*='ddlProducts']")
        if await product_dd.count() == 0:
            product_dd = p.locator("select").filter(has_text="PPA Value").first
        await product_dd.select_option(label="Custom360 Package")
        console.print("  Product: Custom360 Package")
        await asyncio.sleep(1)

        # Click Begin
        await p.click("#ContentPlaceHolder1_btnBeginQuote, input[value='Begin']")
        console.print("  → Begin clicked")

        await p.wait_for_load_state("networkidle")
        await asyncio.sleep(2)
        await self.shot("client_search")

    # ═══ SCREEN 3: CLIENT SEARCH ═══
    # URL: ho.natgenagency.com/ContentPages/ClientSearch
    # Fields: First Name*, Last Name*, Zip Code*
    # Button: Search
    # If no match: shows "Add New Customer" link/button

    async def client_search(self, data):
        console.print(Panel("Screen 3: Client Search", style="cyan"))
        p = self.page

        # Try specific IDs first, then fallback to positional
        try:
            await p.fill("#txtFirstName, input[id*='txtFirstName']", data.first_name)
            await p.fill("#txtLastName, input[id*='txtLastName']", data.last_name)
            await p.fill("#txtZipCode, input[id*='txtZip']", data.zip_code)
        except Exception:
            inputs = p.locator("input[type='text']")
            await inputs.nth(0).fill(data.first_name)
            await inputs.nth(1).fill(data.last_name)
            await inputs.nth(2).fill(data.zip_code)

        console.print(f"  Search: {data.first_name} {data.last_name}, {data.zip_code}")

        await p.click("input[value='Search'], #btnSearch")
        await p.wait_for_load_state("networkidle")
        await asyncio.sleep(2)
        await self.shot("search_results")

        # Look for "Add New Customer" or proceed if already on ClientInfo
        content = await p.content()
        if "Add New Customer" in content:
            console.print("  No match → Add New Customer")
            await p.click("text=Add New Customer")
            await p.wait_for_load_state("networkidle")
            await asyncio.sleep(2)
        elif "ClientInfo" in p.url:
            console.print("  → Client Info page loaded")
        else:
            try:
                await p.click("text=Add New Customer", timeout=3000)
                await p.wait_for_load_state("networkidle")
                await asyncio.sleep(2)
            except Exception:
                pass

        await self.shot("client_info_page")

    # ═══ SCREEN 4: CLIENT INFORMATION ═══
    # URL: ho.natgenagency.com/ContentPages/ClientInfo
    # LEFT COLUMN:
    #   General Info: Agent (9026649, readonly), Producer (dropdown), Input By, Plan (readonly), Effective Date
    #   Named Insured: First Name, Middle Name, Last Name, Suffix (dropdown: None),
    #     Date of Birth, Social Security (3 fields), Gender (dropdown), Marital Status (dropdown),
    #     Occupation (dropdown), Co-applicant (dropdown: No)
    # RIGHT COLUMN:
    #   Contact: Phone #1 (type dropdown + 3 number fields), Email, Confirm Email,
    #     Opt-In Transactional E-mails (dropdown: No),
    #     Consent for Policy and Driver Service Calls and Texts (dropdown: Yes)
    #   Residential Address: Street Address 1, Street Address 2, City, State (readonly),
    #     Zip Code (readonly), Different mailing address (dropdown: No),
    #     Deed Correction (dropdown: No), Have you been at residence <3 years? (dropdown: No)
    # BOTTOM: Consumer Reports consent text
    # BUTTON: "Next"

    async def fill_client_info(self, data):
        console.print(Panel("Screen 4: Client Information", style="cyan"))
        p = self.page

        # ── Effective Date ──
        if data.effective_date:
            for sel in ["#txtEffectiveDate", "input[id*='EffectiveDate']", "input[name*='EffectiveDate']"]:
                el = p.locator(sel)
                if await el.count() > 0:
                    await el.clear()
                    await el.fill(data.effective_date)
                    console.print(f"  Effective: {data.effective_date}")
                    break

        # ── Named Insured ──
        # First/Last may be pre-filled from search — only fill if empty
        for field, val in [("FirstName", data.first_name), ("LastName", data.last_name)]:
            for sel in [f"#txt{field}", f"input[id*='{field}']"]:
                el = p.locator(sel)
                if await el.count() > 0:
                    cur = await el.first.input_value()
                    if not cur.strip():
                        await el.first.fill(val)
                    break
        console.print(f"  Insured: {data.first_name} {data.last_name}")

        # DOB
        if data.dob:
            for sel in ["#txtDOB", "#txtDateOfBirth", "input[id*='DOB']", "input[id*='DateOfBirth']"]:
                el = p.locator(sel)
                if await el.count() > 0:
                    await el.first.clear()
                    await el.first.fill(data.dob)
                    console.print(f"  DOB: {data.dob}")
                    break

        # Gender dropdown
        for sel in ["#ddlGender", "select[id*='Gender']"]:
            el = p.locator(sel)
            if await el.count() > 0:
                await el.select_option(label=data.gender)
                console.print(f"  Gender: {data.gender}")
                break

        # Marital Status dropdown
        for sel in ["#ddlMaritalStatus", "select[id*='Marital']"]:
            el = p.locator(sel)
            if await el.count() > 0:
                await el.select_option(label=data.marital_status)
                console.print(f"  Marital: {data.marital_status}")
                break

        # Occupation dropdown — default "Other"
        for sel in ["#ddlOccupation", "select[id*='Occupation']"]:
            el = p.locator(sel)
            if await el.count() > 0:
                await el.select_option(label=data.occupation)
                console.print(f"  Occupation: {data.occupation}")
                break

        # Co-applicant: No
        for sel in ["#ddlCoApplicant", "select[id*='CoApplicant']", "select[id*='coApplicant']"]:
            el = p.locator(sel)
            if await el.count() > 0:
                await el.select_option(label="No")
                break

        # ── Contact (Right Side) ──
        phone = data.phone.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
        if len(phone) >= 10:
            # Phone type
            for sel in ["#ddlPhone1Type", "select[id*='Phone1Type']", "select[id*='PhoneType']"]:
                el = p.locator(sel)
                if await el.count() > 0:
                    await el.select_option(label=data.phone_type)
                    break

            # Phone number — 3 separate inputs (area, prefix, line)
            phone_inputs = p.locator("input[id*='Phone1']")
            if await phone_inputs.count() >= 3:
                await phone_inputs.nth(0).fill(phone[:3])
                await phone_inputs.nth(1).fill(phone[3:6])
                await phone_inputs.nth(2).fill(phone[6:10])
            else:
                # Try single input
                for sel in ["#txtPhone1", "input[id*='Phone']"]:
                    el = p.locator(sel)
                    if await el.count() > 0:
                        await el.first.fill(phone)
                        break
            console.print(f"  Phone: ({phone[:3]}) {phone[3:6]}-{phone[6:]}")

        # Email + Confirm Email
        if data.email:
            for sel in ["#txtEmail", "input[id*='Email']"]:
                el = p.locator(sel)
                if await el.count() > 0:
                    await el.first.fill(data.email)
                    break
            for sel in ["#txtConfirmEmail", "input[id*='ConfirmEmail']"]:
                el = p.locator(sel)
                if await el.count() > 0:
                    await el.first.fill(data.email)
                    break
            console.print(f"  Email: {data.email}")

        # Opt-in emails: No
        for sel in ["#ddlOptIn", "select[id*='OptIn']"]:
            el = p.locator(sel)
            if await el.count() > 0:
                await el.select_option(label="No")
                break

        # Consent calls/texts: Yes
        for sel in ["#ddlConsent", "select[id*='Consent']"]:
            el = p.locator(sel)
            if await el.count() > 0:
                await el.select_option(label="Yes")
                console.print("  Consent: Yes")
                break

        # ── Residential Address ──
        if data.address:
            for sel in ["#txtAddress1", "input[id*='Address1']", "input[id*='StreetAddress']"]:
                el = p.locator(sel)
                if await el.count() > 0:
                    await el.first.fill(data.address)
                    console.print(f"  Address: {data.address}")
                    break

        if data.city:
            for sel in ["#txtCity", "input[id*='City']"]:
                el = p.locator(sel)
                if await el.count() > 0:
                    await el.first.fill(data.city)
                    console.print(f"  City: {data.city}")
                    break

        # State + Zip pre-filled from search

        # Deed Correction: No
        for sel in ["#ddlDeedCorrection", "select[id*='Deed']"]:
            el = p.locator(sel)
            if await el.count() > 0:
                await el.select_option(label="No")
                break

        # Residence <3 years: No
        for sel in ["#ddlResidence3Yr", "select[id*='Residence']"]:
            el = p.locator(sel)
            if await el.count() > 0:
                await el.select_option(label=data.at_residence_3_years)
                break

        # Different mailing: No
        for sel in ["#ddlDiffMailing", "select[id*='Mailing']"]:
            el = p.locator(sel)
            if await el.count() > 0:
                await el.select_option(label="No")
                break

        await self.shot("client_info_filled")

        # Click Next
        console.print("  → Next")
        await p.click("input[value='Next'], #btnNext, a:has-text('Next')")
        await p.wait_for_load_state("networkidle")
        await asyncio.sleep(2)
        await self.shot("property_info_page")
        console.print("[green]  ✓ Client Info complete → Property Information[/]")

    # ═══ SCREENS 5+: TODO — waiting for walkthrough ═══
    async def fill_property_info(self, data):
        console.print(Panel("Screen 5: Property Information — [yellow]AWAITING MAPPING[/]", style="cyan"))
        await self.shot("property_info")
        console.print("  [yellow]⏸ Bot paused. Screenshot the Property Info page to continue mapping.[/]")

    async def run_quote(self, data):
        console.print(Panel(
            f"[bold]{data.first_name} {data.last_name}[/]\n"
            f"{data.address}, {data.city}, {data.state} {data.zip_code}\n"
            f"DOB: {data.dob} | Phone: {data.phone} | Product: Custom360 Package",
            title="🤖 ORBIT Quoting Bot — National General", style="cyan"))

        await self.login()
        await self.start_new_quote(data)
        await self.client_search(data)
        await self.fill_client_info(data)
        await self.fill_property_info(data)
        return data

    async def close(self):
        if self.browser: await self.browser.close()
        if hasattr(self, 'pw'): await self.pw.stop()


# ── CLI ──
async def cmd_test_login():
    bot = NatGenBot()
    await bot.start()
    try:
        await bot.login()
        input("\nPress Enter to close browser...")
    finally:
        await bot.close()

async def cmd_screenshot():
    bot = NatGenBot()
    await bot.start()
    try:
        await bot.login()
        console.print("\n[cyan]Navigate manually, press Enter to screenshot each page.[/]")
        step = 1
        while True:
            name = Prompt.ask(f"Step {step} name (or 'done')")
            if name.lower() == "done": break
            await bot.shot(name.replace(" ", "_"))
            step += 1
    finally:
        await bot.close()

async def cmd_quote(lead_id=None):
    data = QuoteData()
    if lead_id:
        console.print(f"Fetching lead #{lead_id}...")
        orbit = OrbitClient().login()
        data = QuoteData.from_orbit_lead(orbit.get_lead(lead_id))
    else:
        console.print(Panel("Manual Quote Entry", style="cyan"))
        data.first_name = Prompt.ask("First name")
        data.last_name = Prompt.ask("Last name")
        data.dob = Prompt.ask("DOB (MM/DD/YYYY)")
        data.gender = Prompt.ask("Gender", choices=["Male", "Female"], default="Male")
        data.marital_status = Prompt.ask("Marital status", choices=["Single", "Married"], default="Single")
        data.address = Prompt.ask("Street address")
        data.city = Prompt.ask("City")
        data.state = Prompt.ask("State", default="IL")
        data.zip_code = Prompt.ask("ZIP")
        data.phone = Prompt.ask("Phone", default="8888888888")
        data.email = Prompt.ask("Email", default="")
        data.effective_date = Prompt.ask("Effective date", default=date.today().strftime("%m/%d/%Y"))

    bot = NatGenBot()
    await bot.start()
    try:
        await bot.run_quote(data)
        t = Table(title="Quote Progress")
        t.add_column("Field", style="cyan"); t.add_column("Value")
        t.add_row("Name", f"{data.first_name} {data.last_name}")
        t.add_row("Address", f"{data.address}, {data.city}, {data.state} {data.zip_code}")
        t.add_row("Screens Done", "Login ✓ → Dashboard ✓ → Search ✓ → Client Info ✓")
        t.add_row("Next", "Property Information (needs mapping)")
        console.print(t)
        input("\nPress Enter to close browser...")
    finally:
        await bot.close()

class OrbitClient:
    def __init__(self):
        import httpx
        self.api = ORBIT_API; self.client = httpx.Client(timeout=30); self.token = None
    def login(self):
        r = self.client.post(f"{self.api}/api/auth/login", data={"username": os.getenv("ORBIT_USERNAME", "admin"), "password": os.getenv("ORBIT_PASSWORD", "admin123")}, headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.token = r.json()["access_token"]; return self
    def headers(self): return {"Authorization": f"Bearer {self.token}"}
    def get_lead(self, lid): return self.client.get(f"{self.api}/api/quotes/{lid}", headers=self.headers()).json()

def main():
    if len(sys.argv) < 2:
        console.print(Panel("[bold]ORBIT Quoting Bot — National General[/]\n\n  python bot.py test-login\n  python bot.py screenshot\n  python bot.py quote --manual\n  python bot.py quote --lead-id 123", style="cyan"))
        return
    cmd = sys.argv[1]
    if cmd == "test-login": asyncio.run(cmd_test_login())
    elif cmd == "screenshot": asyncio.run(cmd_screenshot())
    elif cmd == "quote":
        lid = int(sys.argv[sys.argv.index("--lead-id") + 1]) if "--lead-id" in sys.argv else None
        asyncio.run(cmd_quote(lid))
    else: console.print(f"[red]Unknown: {cmd}[/]")

if __name__ == "__main__":
    main()
