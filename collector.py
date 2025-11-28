import asyncio
import logging
import os
import sys
import time
from typing import Dict, Optional, List

from playwright.async_api import async_playwright, Page, BrowserContext
from playwright_stealth import Stealth
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Twitch Channels
CHANNELS_ENV = os.getenv("CHANNELS", "")
CHANNELS = [c.strip() for c in CHANNELS_ENV.split(",") if c.strip()]

# Twitch Username
MY_USERNAME = os.getenv("MY_USERNAME")

# Browser Configuration
HEADLESS = os.getenv("HEADLESS", "False").lower() == "true"
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "twitch_user_data")

# Timings
TAB_SWITCH_DELAY = 30
OFFLINE_COOLDOWN = 3600  # 1 hour
RESTART_INTERVAL = 14400 # 4 hours

class TwitchFarmer:
    def __init__(self):
        self.channel_states: Dict[str, Dict] = {
            name: {"page": None, "next_check": 0} for name in CHANNELS
        }

    async def launch_browser(self, p) -> BrowserContext:
        logging.info(f"Launching browser with user data dir: {USER_DATA_DIR}")
        # Use a standard user agent to avoid detection/mobile views
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=HEADLESS,
            channel="chrome",
            user_agent=user_agent,
            viewport={"width": 1920, "height": 1080},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-size=1920,1080",
                "--disable-infobars",
                "--excludeSwitches=enable-automation",
                "--use-fake-ui-for-media-stream",
            ]
        )
        
        # Apply stealth to all pages created in this context
        await Stealth().apply_stealth_async(context.pages[0])
        
        # Remove navigator.webdriver property
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        return context

    async def check_channel_status(self, page: Page, name: str) -> bool:
        """Checks if the channel is offline. Returns True if offline."""
        is_offline = False
        
        # 1. Check for "Chat" tab (standard offline view)
        try:
            chat_tab = page.get_by_role("tab", name="Chat")
            if await chat_tab.is_visible():
                is_offline = True
        except Exception:
            pass

        # 2. Check for missing video player
        if not is_offline:
            try:
                if not await page.locator("video").first.is_visible():
                    is_offline = True
                    logging.info(f"[{name}] Video player not visible. Assuming OFFLINE.")
            except Exception:
                pass
        
        return is_offline

    async def claim_bonus(self, page: Page, name: str):
        """Checks for and claims the bonus chest."""
        bonus_selector = "button[aria-label='Claim Bonus']"
        try:
            if await page.locator(bonus_selector).count() > 0:
                if await page.locator(bonus_selector).is_visible():
                    logging.info(f"[{name}] Bonus detected! Clicking...")
                    await page.click(bonus_selector)
                    logging.info(f"[{name}] Clicked bonus chest!")
        except Exception as e:
            logging.error(f"[{name}] Error claiming bonus: {e}")

    async def log_channel_points(self, page: Page, name: str):
        """Logs the current channel points."""
        try:
            balance_selector = '[data-test-selector="balance-string"]'
            if await page.locator(balance_selector).is_visible():
                points = await page.locator(balance_selector).inner_text()
                logging.info(f"[{name}] Current Channel Points: {points}")
        except Exception:
            pass

    async def check_chat_list(self, page: Page, name: str):
        """Checks if MY_USERNAME is present in the chat list."""
        if not MY_USERNAME:
            return

        logging.info(f"[{name}] Checking if '{MY_USERNAME}' is in chat list...")
        try:
            # Check for "Close Threads" button first (if we are in a thread)
            close_threads_btn = page.locator("button[aria-label='Close Threads']")
            if await close_threads_btn.is_visible():
                logging.info(f"[{name}] 'Close Threads' button found. Clicking to return to main chat...")
                await close_threads_btn.click()
                await asyncio.sleep(1)

            community_btn = page.locator("button[aria-label='Community']")
            if await community_btn.is_visible():
                await community_btn.click(timeout=3000)
                
                try:
                    # Increased wait time for the list to load
                    await asyncio.sleep(3)
                    
                    # Explicitly wait for the filter input
                    search_input = page.get_by_placeholder("Filter", exact=False)
                    try:
                        await search_input.wait_for(state="visible", timeout=5000)
                    except:
                        pass # Handle in the if block below
                    
                    if await search_input.is_visible():
                        logging.info(f"[{name}] Filtering for '{MY_USERNAME}'...")
                        await search_input.click()
                        await search_input.fill(MY_USERNAME)
                        await asyncio.sleep(1)
                    else:
                        logging.warning(f"[{name}] Warning: Could not find 'Filter' input. Checking visible list only.")
                        if HEADLESS:
                            try:
                                timestamp = int(time.time())
                                debug_file_img = f"debug_headless_{name}_{timestamp}.png"
                                debug_file_html = f"debug_headless_{name}_{timestamp}.html"
                                
                                await page.screenshot(path=debug_file_img)
                                with open(debug_file_html, "w", encoding="utf-8") as f:
                                    f.write(await page.content())
                                    
                                logging.info(f"[{name}] Saved debug screenshot to {debug_file_img} and HTML to {debug_file_html}")
                            except Exception as e:
                                logging.error(f"[{name}] Failed to save debug info: {e}")

                    if await page.get_by_text(MY_USERNAME, exact=True).is_visible():
                        logging.info(f"[{name}] STATUS: '{MY_USERNAME}' FOUND in chat list! ✅")
                    else:
                        logging.info(f"[{name}] STATUS: '{MY_USERNAME}' NOT FOUND in chat list. ❌")
                finally:
                    # Close the list
                    try:
                        back_btn = page.locator("button[aria-label='Go back to Chat']")
                        if await back_btn.count() == 0:
                            back_btn = page.locator("button[aria-label='Close']")
                        
                        if await back_btn.is_visible():
                            await back_btn.click(timeout=3000)
                            logging.info(f"[{name}] Closed community tab.")
                        elif await community_btn.is_visible():
                            await community_btn.click(timeout=3000)
                            logging.info(f"[{name}] Closed community tab (Toggle).")
                        else:
                            logging.warning(f"[{name}] Warning: Could not find button to close list.")
                    except Exception as e:
                        logging.warning(f"[{name}] Warning: Could not close community tab: {e}")
            else:
                logging.warning(f"[{name}] Could not find Community button.")
        except Exception as e:
            logging.error(f"[{name}] Error checking chat list: {e}")

    async def process_channel(self, context: BrowserContext, name: str, current_time: float):
        state = self.channel_states[name]
        page = state["page"]
        next_check = state["next_check"]

        # Open tab if needed
        if page is None:
            if current_time >= next_check:
                logging.info(f"[{name}] Checking channel (opening tab)...")
                try:
                    new_page = await context.new_page()
                    await new_page.goto(f"https://www.twitch.tv/{name}")
                    state["page"] = new_page
                    await asyncio.sleep(5) # Wait for load
                except Exception as e:
                    logging.error(f"[{name}] Error opening tab: {e}")
            return

        # Process open tab
        try:
            # Bring to front
            try:
                await page.bring_to_front()
            except Exception:
                state["page"] = None
                return

            # Check for Raid / URL change
            current_url = page.url.lower()
            expected_url = f"https://www.twitch.tv/{name}".lower()
            if current_url != expected_url and not current_url.startswith(expected_url + "/") and not current_url.startswith(expected_url + "?"):
                logging.info(f"[{name}] URL changed to {page.url} (Raid detected). Closing tab.")
                await page.close()
                state["page"] = None
                state["next_check"] = current_time + OFFLINE_COOLDOWN
                return

            # Check Offline
            if await self.check_channel_status(page, name):
                logging.info(f"[{name}] Stream appears OFFLINE. Closing tab for 1 hour.")
                await page.close()
                state["page"] = None
                state["next_check"] = current_time + OFFLINE_COOLDOWN
                return

            # Enforce volume
            try:
                await page.evaluate("""
                    const video = document.querySelector('video');
                    if (video) {
                        if (video.volume !== 0.01 || video.muted) {
                            video.volume = 0.01;
                            video.muted = false;
                        }
                    }
                """)
            except Exception:
                pass

            # Claim Bonus
            await self.claim_bonus(page, name)

            # Log Channel Points
            await self.log_channel_points(page, name)

            # Wait
            await asyncio.sleep(TAB_SWITCH_DELAY)

            # Check Chat List (Only if not headless)
            if not HEADLESS:
                await self.check_chat_list(page, name)

        except Exception as e:
            logging.error(f"[{name}] Error processing: {e}")
            try:
                await page.close()
            except:
                pass
            state["page"] = None

    async def run(self):
        async with async_playwright() as p:
            context = await self.launch_browser(p)
            
            logging.info("Monitoring started. Channels will be checked periodically.")
            logging.info("IMPORTANT: If you are not logged in, please log in manually in the browser window now.")

            start_time = time.time()
            while True:
                if time.time() - start_time > RESTART_INTERVAL:
                    logging.info(f"Restart interval of {RESTART_INTERVAL}s reached. Restarting script...")
                    break

                current_time = time.time()
                for name in CHANNELS:
                    await self.process_channel(context, name, current_time)
                
                await asyncio.sleep(2)

if __name__ == "__main__":
    should_restart = True
    try:
        farmer = TwitchFarmer()
        asyncio.run(farmer.run())
    except KeyboardInterrupt:
        logging.info("Script stopped by user.")
        should_restart = False
    except Exception as e:
        logging.critical(f"Unexpected error: {e}")
        should_restart = False

    if should_restart:
        logging.info("Re-executing script to apply updates...")
        os.execv(sys.executable, [sys.executable] + sys.argv)
