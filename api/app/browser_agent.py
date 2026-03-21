import asyncio
import base64
import json
from typing import AsyncGenerator

from playwright.async_api import async_playwright, Page


FIELD_HINTS: dict[str, list[str]] = {
    "name":         ["name", "full name", "fullname", "full_name", "applicant"],
    "email":        ["email", "e-mail", "email address", "email_address"],
    "phone":        ["phone", "mobile", "telephone", "tel", "contact number"],
    "cover_letter": ["cover", "letter", "message", "motivation", "statement", "additional information"],
}

DONE_COMMANDS = {"submit", "done", "skip", "cancel", "abort"}


async def _screenshot_b64(page: Page) -> str:
    png = await page.screenshot(full_page=False)
    return base64.b64encode(png).decode()


async def _fill_field(page: Page, value: str, hints: list[str]) -> bool:
    """Try common selector strategies to fill a field. Returns True if filled."""
    for hint in hints:
        for strategy in [
            lambda h: page.get_by_label(h, exact=False),
            lambda h: page.locator(f'input[name*="{h}" i], textarea[name*="{h}" i]'),
            lambda h: page.locator(f'input[placeholder*="{h}" i], textarea[placeholder*="{h}" i]'),
            lambda h: page.locator(f'input[id*="{h}" i], textarea[id*="{h}" i]'),
        ]:
            try:
                loc = strategy(hint)
                if await loc.count() > 0 and await loc.first.is_visible():
                    await loc.first.fill(value)
                    return True
            except Exception:
                pass
    return False


def _detect_blocked(content: str) -> tuple[bool, str | None]:
    lower = content.lower()
    if any(kw in lower for kw in ["sign in to apply", "log in to apply", "login to apply", "create an account to apply", "suspicious", "unusual behaviour"]):
        return True, "Login or verification required — take over below"
    if any(kw in lower for kw in ["captcha", "i'm not a robot", "verify you are human", "prove you're human"]):
        return True, "CAPTCHA detected — complete it below"
    return False, None


async def _interactive_session(page: Page, instruction_queue: asyncio.Queue) -> AsyncGenerator[dict, None]:
    """
    Hand control to the user. Loops processing commands from instruction_queue:
      { "type": "click", "x": N, "y": N }
      { "type": "type", "text": "..." }
      { "type": "key", "key": "Enter" }
      { "type": "scroll", "delta": N }
      plain text "submit" / "skip" / "done" → exits loop

    Yields a fresh screenshot after every command.
    """
    screenshot = await _screenshot_b64(page)
    yield {
        "action": "You have control — click the screenshot or type below",
        "screenshot": screenshot,
        "blocked": True,
        "reason": "Click anywhere on the screenshot to interact, type in the box, or type 'submit' / 'skip'.",
        "done": False,
        "interactive": True,
    }

    while True:
        try:
            raw = await asyncio.wait_for(instruction_queue.get(), timeout=300)
        except asyncio.TimeoutError:
            yield {"action": "Session timed out", "screenshot": None, "blocked": False, "reason": None, "done": True}
            return

        # Try to parse as structured command
        cmd: dict | None = None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "type" in parsed:
                cmd = parsed
        except (json.JSONDecodeError, TypeError):
            pass

        if cmd:
            kind = cmd.get("type", "")
            if kind == "click":
                await page.mouse.click(float(cmd["x"]), float(cmd["y"]))
                await page.wait_for_timeout(600)
            elif kind == "type":
                await page.keyboard.type(str(cmd.get("text", "")))
                await page.wait_for_timeout(200)
            elif kind == "key":
                await page.keyboard.press(str(cmd.get("key", "Enter")))
                await page.wait_for_timeout(400)
            elif kind == "scroll":
                await page.mouse.wheel(0, float(cmd.get("delta", 300)))
                await page.wait_for_timeout(300)
            elif kind in DONE_COMMANDS or cmd.get("type") in DONE_COMMANDS:
                yield {"action": f"User ended session: {kind}", "screenshot": None, "blocked": False, "reason": None, "done": True}
                return

            screenshot = await _screenshot_b64(page)
            yield {
                "action": f"Executed: {kind}",
                "screenshot": screenshot,
                "blocked": True,
                "reason": "Click the screenshot or type below. Type 'submit' when done.",
                "done": False,
                "interactive": True,
            }

        else:
            # Plain text command
            text = str(raw).strip().lower()
            if text in DONE_COMMANDS:
                if text in ("skip", "cancel", "abort"):
                    yield {"action": "Cancelled by user", "screenshot": None, "blocked": False, "reason": None, "done": True}
                else:
                    yield {"action": "User confirmed — proceeding", "screenshot": None, "blocked": False, "reason": None, "done": True}
                return
            # Treat as keyboard input
            await page.keyboard.type(str(raw))
            await page.wait_for_timeout(200)
            screenshot = await _screenshot_b64(page)
            yield {
                "action": f"Typed: {raw[:40]}",
                "screenshot": screenshot,
                "blocked": True,
                "reason": "Click the screenshot or type below. Type 'submit' when done.",
                "done": False,
                "interactive": True,
            }


async def apply_with_browser(
    job_url: str,
    cv_profile: dict,
    cover_letter: str,
    instruction_queue: asyncio.Queue,
) -> AsyncGenerator[dict, None]:
    """
    Async generator — navigate to job_url and attempt to fill the application form.

    Yields dicts:
        { action, screenshot (base64|None), blocked (bool), reason (str|None), done (bool) }

    Provides interactive takeover via _interactive_session() at both block points and
    the pre-submit review pause.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1280,800",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
            window.chrome = { runtime: {} };
        """)

        try:
            # 1. Navigate
            yield {"action": "Navigating to job listing…", "screenshot": None, "blocked": False, "reason": None, "done": False}
            try:
                await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                yield {"action": f"Navigation failed: {e}", "screenshot": None, "blocked": False, "reason": None, "done": True}
                return
            await page.wait_for_timeout(1500)

            screenshot = await _screenshot_b64(page)
            yield {"action": "Arrived at job page", "screenshot": screenshot, "blocked": False, "reason": None, "done": False}

            # 2. Check for hard blockers — hand to interactive session if blocked
            content = await page.content()
            blocked, reason = _detect_blocked(content)
            if blocked:
                screenshot = await _screenshot_b64(page)
                yield {"action": "Blocked — handing control to you", "screenshot": screenshot, "blocked": True, "reason": reason, "done": False}
                async for step in _interactive_session(page, instruction_queue):
                    yield step
                    if step.get("done"):
                        return
                # After user takes over, take fresh screenshot and continue
                await page.wait_for_timeout(500)

            # 3. Find and click Apply button
            apply_selectors = [
                'a:has-text("Apply now")', 'button:has-text("Apply now")',
                'a:has-text("Apply")', 'button:has-text("Apply")',
                '[data-testid*="apply"]', '[aria-label*="apply" i]',
            ]
            clicked = False
            for sel in apply_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click()
                        clicked = True
                        await page.wait_for_timeout(2000)
                        break
                except Exception:
                    pass

            screenshot = await _screenshot_b64(page)
            yield {
                "action": "Clicked Apply — loading form" if clicked else "No Apply button found — attempting direct form fill",
                "screenshot": screenshot,
                "blocked": False,
                "reason": None,
                "done": False,
            }

            # 4. Auto-fill fields
            fill_map = {
                "name":         cv_profile.get("name", ""),
                "email":        cv_profile.get("email", ""),
                "phone":        cv_profile.get("phone", ""),
                "cover_letter": cover_letter,
            }
            for field_key, value in fill_map.items():
                if not value:
                    continue
                filled = await _fill_field(page, value, FIELD_HINTS[field_key])
                if filled:
                    yield {"action": f"Filled {field_key.replace('_', ' ')}", "screenshot": None, "blocked": False, "reason": None, "done": False}

            # 5. Hand to interactive session for review + submit
            async for step in _interactive_session(page, instruction_queue):
                yield step
                if step.get("done"):
                    return

        finally:
            await browser.close()
