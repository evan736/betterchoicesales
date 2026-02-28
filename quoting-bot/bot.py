"""
ORBIT Quoting Bot — National General
Browser automation for auto-quoting homeowners + auto policies.
Runs locally on agent's machine with visual browser.

Usage:
    python bot.py quote --lead-id 123        # Quote a specific lead from ORBIT
    python bot.py quote --manual              # Enter quote data manually
    python bot.py test-login                  # Test NatGen portal login
    python bot.py screenshot                  # Take screenshots of each step (for mapping)
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.panel import Panel

load_dotenv()
console = Console()

# ── Config ──
NATGEN_URL = os.getenv("NATGEN_PORTAL_URL", "https://natgenagency.com")
NATGEN_USER = os.getenv("NATGEN_USERNAME", "")
NATGEN_PASS = os.getenv("NATGEN_PASSWORD", "")
ORBIT_API = os.getenv("ORBIT_API_URL", "https://better-choice-api.onrender.com")
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO = int(os.getenv("SLOW_MO", "500"))
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "./screenshots"))
SCREENSHOT_DIR.mkdir(exist_ok=True)


# ── Quote Data Model ──
# This holds ALL fields needed to fill out a NatGen quote.
# Fields will be populated from ORBIT lead data or manual entry.

class QuoteData:
    """All fields needed for a NatGen homeowners + auto quote."""

    def __init__(self):
        # ── Applicant Info ──
        self.first_name: str = ""
        self.last_name: str = ""
        self.dob: str = ""           # MM/DD/YYYY
        self.ssn: str = ""           # Optional, for credit-based pricing
        self.email: str = ""
        self.phone: str = ""

        # ── Property Address ──
        self.address: str = ""
        self.city: str = ""
        self.state: str = "IL"
        self.zip_code: str = ""

        # ── Property Details (Homeowners) ──
        self.year_built: str = ""
        self.roof_year: str = ""
        self.sqft: str = ""
        self.construction_type: str = ""    # Frame, Masonry, etc.
        self.roof_type: str = ""            # Asphalt shingle, Metal, Tile, etc.
        self.heating_type: str = ""         # Forced air, Baseboard, etc.
        self.foundation_type: str = ""      # Basement, Slab, Crawlspace
        self.num_stories: str = ""          # 1, 1.5, 2, 2.5, 3
        self.dwelling_type: str = ""        # Single family, Condo, Townhouse
        self.protection_class: str = ""     # 1-10
        self.dist_fire_station: str = ""    # Miles
        self.dist_fire_hydrant: str = ""    # Feet

        # ── Coverages (Homeowners) ──
        self.coverage_a: str = ""           # Dwelling
        self.coverage_b: str = ""           # Other structures (% of A)
        self.coverage_c: str = ""           # Personal property (% of A)
        self.coverage_d: str = ""           # Loss of use (% of A)
        self.coverage_e: str = ""           # Personal liability
        self.coverage_f: str = ""           # Medical payments
        self.deductible: str = ""           # $1000, $2500, etc.
        self.wind_hail_deductible: str = "" # Separate wind/hail deductible

        # ── Auto / Vehicles ──
        self.vehicles: list = []            # List of vehicle dicts
        # Each vehicle: {year, make, model, vin, usage, annual_miles, garaging_zip}

        # ── Drivers ──
        self.drivers: list = []             # List of driver dicts
        # Each driver: {first_name, last_name, dob, license_number, license_state, gender, marital_status, relationship}

        # ── Auto Coverages ──
        self.bodily_injury: str = ""        # 100/300, 250/500, etc.
        self.property_damage: str = ""      # 100000, etc.
        self.um_uim: str = ""               # Uninsured/underinsured
        self.comp_deductible: str = ""      # $500, $1000
        self.collision_deductible: str = "" # $500, $1000
        self.rental: str = ""               # Yes/No + limit
        self.roadside: str = ""             # Yes/No

        # ── Current Insurance ──
        self.current_carrier: str = ""
        self.current_premium: str = ""
        self.years_with_carrier: str = ""
        self.prior_claims: list = []        # List of {date, type, amount}

        # ── Quote Result (filled by bot after quoting) ──
        self.quoted_premium: str = ""
        self.quote_number: str = ""
        self.quoted_at: str = ""
        self.screenshots: list = []         # Paths to screenshots taken during quoting

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict):
        q = cls()
        for k, v in d.items():
            if hasattr(q, k):
                setattr(q, k, v)
        return q

    @classmethod
    def from_orbit_lead(cls, lead: dict):
        """Populate from ORBIT lead/quote data."""
        q = cls()
        q.first_name = lead.get("first_name", "")
        q.last_name = lead.get("last_name", "")
        q.email = lead.get("email", "")
        q.phone = lead.get("phone", "")
        q.dob = lead.get("dob", "")
        q.address = lead.get("address", "")
        q.city = lead.get("city", "")
        q.state = lead.get("state", "IL")
        q.zip_code = lead.get("zip_code", "")
        q.year_built = lead.get("year_built", "") or lead.get("home_year", "")
        q.roof_year = lead.get("roof_year", "")
        q.sqft = lead.get("sqft", "")
        q.current_carrier = lead.get("current_carrier", "")
        q.current_premium = lead.get("current_premium", "")
        # Drivers from lead
        drivers = lead.get("drivers", [])
        if drivers:
            q.drivers = drivers
        elif q.first_name:
            q.drivers = [{"first_name": q.first_name, "last_name": q.last_name, "dob": q.dob}]
        return q


# ── NatGen Portal Automation ──

class NatGenBot:
    """Playwright automation for NatGen agent portal."""

    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self.screenshot_count = 0

    async def start(self):
        """Launch browser."""
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO,
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1440, "height": 900},
        )
        self.page = await self.context.new_page()
        console.print("[green]✓[/] Browser launched")

    async def screenshot(self, name: str) -> str:
        """Take a screenshot and return the path."""
        self.screenshot_count += 1
        ts = datetime.now().strftime("%H%M%S")
        filename = f"{self.screenshot_count:02d}_{name}_{ts}.png"
        path = SCREENSHOT_DIR / filename
        await self.page.screenshot(path=str(path), full_page=True)
        console.print(f"  📸 Screenshot: {filename}")
        return str(path)

    async def login(self):
        """Log into NatGen agent portal."""
        console.print(Panel("Logging into NatGen Agent Portal...", style="cyan"))

        if not NATGEN_USER or not NATGEN_PASS:
            console.print("[red]✗ NATGEN_USERNAME and NATGEN_PASSWORD must be set in .env[/]")
            return False

        await self.page.goto(f"{NATGEN_URL}")
        await self.page.wait_for_load_state("networkidle")
        await self.screenshot("login_page")

        # ── LOGIN FLOW ──
        # TODO: Map the actual login form fields after Evan describes them
        # Example structure (update after portal walkthrough):
        #
        # await self.page.fill("#username", NATGEN_USER)
        # await self.page.fill("#password", NATGEN_PASS)
        # await self.page.click("#loginButton")
        # await self.page.wait_for_load_state("networkidle")

        console.print("[yellow]⚠ Login flow needs to be mapped — waiting for portal walkthrough[/]")
        return True

    async def navigate_to_new_quote(self, line: str = "homeowners"):
        """Navigate to the new quote page."""
        console.print(f"Navigating to new {line} quote...")

        # TODO: Map the navigation after login
        # Typically: Dashboard → New Quote → Select Line of Business
        #
        # await self.page.click("text=New Quote")
        # await self.page.click(f"text={line.title()}")

        await self.screenshot("new_quote_page")

    async def fill_applicant_info(self, data: QuoteData):
        """Fill in applicant/named insured information."""
        console.print("Filling applicant info...")

        # TODO: Map actual form fields from portal walkthrough
        # Example:
        # await self.page.fill("#firstName", data.first_name)
        # await self.page.fill("#lastName", data.last_name)
        # await self.page.fill("#dob", data.dob)
        # await self.page.fill("#address", data.address)
        # await self.page.fill("#city", data.city)
        # await self.page.select_option("#state", data.state)
        # await self.page.fill("#zip", data.zip_code)

        await self.screenshot("applicant_info")

    async def fill_property_details(self, data: QuoteData):
        """Fill in property details for homeowners."""
        console.print("Filling property details...")

        # TODO: Map actual form fields
        # await self.page.fill("#yearBuilt", data.year_built)
        # await self.page.fill("#roofYear", data.roof_year)
        # await self.page.fill("#sqft", data.sqft)
        # await self.page.select_option("#constructionType", data.construction_type)
        # etc.

        await self.screenshot("property_details")

    async def fill_coverages(self, data: QuoteData):
        """Fill in coverage selections."""
        console.print("Filling coverage selections...")

        # TODO: Map actual coverage fields
        await self.screenshot("coverages")

    async def fill_vehicle_info(self, data: QuoteData):
        """Fill in vehicle information for auto."""
        console.print("Filling vehicle info...")

        for i, vehicle in enumerate(data.vehicles):
            console.print(f"  Vehicle {i+1}: {vehicle.get('year', '')} {vehicle.get('make', '')} {vehicle.get('model', '')}")
            # TODO: Map vehicle form fields

        await self.screenshot("vehicle_info")

    async def fill_driver_info(self, data: QuoteData):
        """Fill in driver information for auto."""
        console.print("Filling driver info...")

        for i, driver in enumerate(data.drivers):
            console.print(f"  Driver {i+1}: {driver.get('first_name', '')} {driver.get('last_name', '')}")
            # TODO: Map driver form fields

        await self.screenshot("driver_info")

    async def submit_quote(self):
        """Submit the quote and capture the premium."""
        console.print("Submitting quote...")

        # TODO: Click rate/submit button and wait for results
        # await self.page.click("#rateQuote")
        # await self.page.wait_for_selector("#quotedPremium")
        # premium = await self.page.text_content("#quotedPremium")

        await self.screenshot("quote_result")
        return None  # Return premium when mapped

    async def run_quote(self, data: QuoteData) -> QuoteData:
        """Full quoting flow — login through result."""
        console.print(Panel(
            f"Quoting: [bold]{data.first_name} {data.last_name}[/]\n"
            f"Address: {data.address}, {data.city}, {data.state} {data.zip_code}\n"
            f"Type: Homeowners + Auto",
            title="🤖 ORBIT Quoting Bot — National General",
            style="cyan",
        ))

        await self.login()
        await self.navigate_to_new_quote("homeowners")
        await self.fill_applicant_info(data)
        await self.fill_property_details(data)
        await self.fill_coverages(data)

        if data.vehicles:
            await self.fill_vehicle_info(data)
        if data.drivers:
            await self.fill_driver_info(data)

        premium = await self.submit_quote()

        if premium:
            data.quoted_premium = premium
            data.quoted_at = datetime.now().isoformat()
            console.print(f"\n[bold green]✓ Quoted Premium: ${premium}[/]")
        else:
            console.print("\n[yellow]⚠ Quote flow incomplete — portal mapping needed[/]")

        return data

    async def close(self):
        """Clean up."""
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'pw'):
            await self.pw.stop()


# ── ORBIT API Client ──

class OrbitClient:
    """Pull lead data from ORBIT and push back results."""

    def __init__(self):
        import httpx
        self.api = ORBIT_API
        self.token = None
        self.client = httpx.Client(timeout=30)

    def login(self):
        r = self.client.post(
            f"{self.api}/api/auth/login",
            data={"username": os.getenv("ORBIT_USERNAME", "admin"), "password": os.getenv("ORBIT_PASSWORD", "admin123")},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.token = r.json()["access_token"]
        return self

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get_lead(self, lead_id: int) -> dict:
        """Fetch lead data from ORBIT."""
        r = self.client.get(f"{self.api}/api/quotes/{lead_id}", headers=self.headers())
        return r.json()

    def save_quote_result(self, lead_id: int, result: dict):
        """Push quote result back to ORBIT."""
        r = self.client.post(
            f"{self.api}/api/quotes/{lead_id}/bot-result",
            json=result,
            headers=self.headers(),
        )
        return r.json()


# ── CLI ──

async def cmd_test_login():
    """Test logging into NatGen portal."""
    bot = NatGenBot()
    await bot.start()
    try:
        await bot.login()
        console.print("\n[green]Login test complete. Check screenshots/ folder.[/]")
        input("Press Enter to close browser...")
    finally:
        await bot.close()


async def cmd_screenshot_flow():
    """Walk through the portal and take screenshots of every page."""
    bot = NatGenBot()
    await bot.start()
    try:
        await bot.login()
        console.print("\n[cyan]Browser is open. Navigate manually and press Enter after each page to screenshot.[/]")
        step = 1
        while True:
            name = Prompt.ask(f"Step {step} name (or 'done' to finish)")
            if name.lower() == "done":
                break
            await bot.screenshot(name.replace(" ", "_"))
            step += 1
    finally:
        await bot.close()


async def cmd_quote(lead_id: int = None):
    """Run a full quote."""
    data = QuoteData()

    if lead_id:
        console.print(f"Fetching lead #{lead_id} from ORBIT...")
        orbit = OrbitClient().login()
        lead = orbit.get_lead(lead_id)
        data = QuoteData.from_orbit_lead(lead)
        console.print(f"[green]✓[/] Loaded: {data.first_name} {data.last_name}")
    else:
        console.print(Panel("Manual Quote Entry", style="cyan"))
        data.first_name = Prompt.ask("First name")
        data.last_name = Prompt.ask("Last name")
        data.dob = Prompt.ask("Date of birth (MM/DD/YYYY)")
        data.address = Prompt.ask("Street address")
        data.city = Prompt.ask("City")
        data.state = Prompt.ask("State", default="IL")
        data.zip_code = Prompt.ask("ZIP code")
        data.email = Prompt.ask("Email", default="")
        data.phone = Prompt.ask("Phone", default="")

    bot = NatGenBot()
    await bot.start()
    try:
        result = await bot.run_quote(data)

        # Summary
        table = Table(title="Quote Summary")
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("Name", f"{result.first_name} {result.last_name}")
        table.add_row("Address", f"{result.address}, {result.city}, {result.state} {result.zip_code}")
        table.add_row("Premium", result.quoted_premium or "Not yet captured")
        table.add_row("Quote #", result.quote_number or "Not yet captured")
        table.add_row("Screenshots", str(len(os.listdir(SCREENSHOT_DIR))))
        console.print(table)

        if lead_id and result.quoted_premium:
            orbit.save_quote_result(lead_id, result.to_dict())
            console.print("[green]✓ Result saved to ORBIT[/]")

        input("\nPress Enter to close browser...")
    finally:
        await bot.close()


def main():
    if len(sys.argv) < 2:
        console.print(Panel(
            "[bold]ORBIT Quoting Bot — National General[/]\n\n"
            "Commands:\n"
            "  python bot.py test-login              Test NatGen portal login\n"
            "  python bot.py screenshot              Interactive screenshot mode\n"
            "  python bot.py quote --lead-id 123     Quote from ORBIT lead\n"
            "  python bot.py quote --manual           Manual quote entry\n",
            style="cyan",
        ))
        return

    cmd = sys.argv[1]

    if cmd == "test-login":
        asyncio.run(cmd_test_login())
    elif cmd == "screenshot":
        asyncio.run(cmd_screenshot_flow())
    elif cmd == "quote":
        lead_id = None
        if "--lead-id" in sys.argv:
            idx = sys.argv.index("--lead-id")
            lead_id = int(sys.argv[idx + 1])
        asyncio.run(cmd_quote(lead_id))
    else:
        console.print(f"[red]Unknown command: {cmd}[/]")


if __name__ == "__main__":
    main()
