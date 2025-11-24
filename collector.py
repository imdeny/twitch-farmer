import asyncio
from playwright.async_api import async_playwright
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
# Add the Twitch channels you want to farm points from here
# Loaded from .env file, comma separated
channels_env = os.getenv("CHANNELS", "")
CHANNELS = [c.strip() for c in channels_env.split(",") if c.strip()]

# Your Twitch Username (set this to check if you are in the chat list)
MY_USERNAME = os.getenv("MY_USERNAME")

# Path to store persistent browser data (cookies, login session)
USER_DATA_DIR = os.path.join(os.getcwd(), "twitch_user_data")

# Time (seconds) to stay on each tab before switching
TAB_SWITCH_DELAY = 30

# Cooldown in seconds for offline channels (1 hour)
OFFLINE_COOLDOWN = 3600 

# Restart interval in seconds (4 hours) to refresh channel list
RESTART_INTERVAL = 14400 

async def run():
    async with async_playwright() as p:
        print(f"Launching browser with user data dir: {USER_DATA_DIR}")
        # Launch persistent context to save login state
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False, # Must be false to see the browser
            channel="chrome", # Use installed Chrome if available, or remove to use bundled Chromium
            args=["--disable-blink-features=AutomationControlled"] # Try to hide automation
        )

        # Track state for each channel
        # Format: { "channel_name": { "page": Page|None, "next_check": timestamp } }
        channel_states = {name: {"page": None, "next_check": 0} for name in CHANNELS}

        print("Monitoring started. Channels will be checked periodically.")
        print("IMPORTANT: If you are not logged in, please log in manually in the browser window now.")

        # Monitoring loop
        start_time = time.time()
        while True:
            # Check for restart
            if time.time() - start_time > RESTART_INTERVAL:
                print(f"Restart interval of {RESTART_INTERVAL}s reached. Restarting script...")
                break

            current_time = time.time()
            
            for name, state in channel_states.items():
                page = state["page"]
                next_check = state["next_check"]

                # 1. If channel is closed and ready to check, open it
                if page is None:
                    if current_time >= next_check:
                        print(f"[{name}] Checking channel (opening tab)...")
                        try:
                            new_page = await context.new_page()
                            await new_page.goto(f"https://www.twitch.tv/{name}")
                            state["page"] = new_page
                            # Give it a moment to load
                            await asyncio.sleep(5)
                        except Exception as e:
                            print(f"[{name}] Error opening tab: {e}")
                    continue # Skip to next channel, let this one load in next cycle

                # 2. If channel is open, process it
                try:
                    # Bring to front to simulate active watching
                    try:
                        await page.bring_to_front()
                    except:
                        # Page might have been closed manually
                        state["page"] = None
                        continue

                    # Check for Raid / URL change
                    current_url = page.url.lower()
                    expected_url = f"https://www.twitch.tv/{name}".lower()
                    if current_url != expected_url and not current_url.startswith(expected_url + "/") and not current_url.startswith(expected_url + "?"):
                        print(f"[{name}] URL changed to {page.url} (Raid detected). Closing tab.")
                        await page.close()
                        state["page"] = None
                        state["next_check"] = current_time + OFFLINE_COOLDOWN
                        continue

                    # Check for Offline Status
                    is_offline = False

                    # 1. Check for "Chat" tab (standard offline view)
                    try:
                        chat_tab = page.get_by_role("tab", name="Chat")
                        if await chat_tab.is_visible():
                            is_offline = True
                    except:
                        pass

                    # 2. Check for missing video player (User suggestion: volume indicator/player missing)
                    if not is_offline:
                        try:
                            # If the video element is not visible, the stream is likely offline
                            # This handles cases where the stream ends but the page doesn't fully refresh to offline mode
                            if not await page.locator("video").first.is_visible():
                                is_offline = True
                                print(f"[{name}] Video player not visible. Assuming OFFLINE.")
                        except:
                            pass

                    if is_offline:
                        print(f"[{name}] Stream appears OFFLINE. Closing tab for 1 hour.")
                        await page.close()
                        state["page"] = None
                        state["next_check"] = current_time + OFFLINE_COOLDOWN
                        continue # Done with this channel for now

                    # If Online (or at least not definitely offline):
                    
                    # Enforce volume settings
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
                    except:
                        pass 

                    # Check for Bonus Button
                    bonus_selector = "button[aria-label='Claim Bonus']"
                    if await page.locator(bonus_selector).count() > 0:
                        if await page.locator(bonus_selector).is_visible():
                            print(f"[{name}] Bonus detected! Clicking...")
                            await page.click(bonus_selector)
                            print(f"[{name}] Clicked bonus chest!")
                    
                    # Stay on this tab for a few seconds
                    await asyncio.sleep(TAB_SWITCH_DELAY)

                    # --- Check if we are in the chat list ---
                    if MY_USERNAME:
                        print(f"[{name}] Checking if '{MY_USERNAME}' is in chat list...")
                        try:
                            # Open Community Tab (Users in Chat)
                            community_btn = page.locator("button[aria-label='Community']")
                            if await community_btn.is_visible():
                                await community_btn.click(timeout=3000)
                                
                                try:
                                    await asyncio.sleep(1) # Wait for list/search bar to appear

                                    # Use the search bar to find the user
                                    # Twitch usually has a "Filter" input in the community tab
                                    search_input = page.get_by_placeholder("Filter", exact=False)
                                    
                                    if await search_input.is_visible():
                                        print(f"[{name}] Filtering for '{MY_USERNAME}'...")
                                        await search_input.click()
                                        await search_input.fill(MY_USERNAME)
                                        await asyncio.sleep(1) # Wait for filter results
                                    else:
                                        print(f"[{name}] Warning: Could not find 'Filter' input. Checking visible list only.")

                                    # Check for username
                                    # We look for the exact text of the username now that we've filtered
                                    if await page.get_by_text(MY_USERNAME, exact=True).is_visible():
                                        print(f"[{name}] STATUS: '{MY_USERNAME}' FOUND in chat list! ✅")
                                    else:
                                        print(f"[{name}] STATUS: '{MY_USERNAME}' NOT FOUND in chat list. ❌")
                                finally:
                                    # Close the list (click "Back to Chat" or "Close" button)
                                    # The user reported we need to click a specific back button, not the community button again.
                                    try:
                                        # Try finding the back button.
                                        # User confirmed the label is "Go back to Chat"
                                        back_btn = page.locator("button[aria-label='Go back to Chat']")
                                        
                                        if await back_btn.count() == 0:
                                            # Fallback: sometimes it might be "Close" or just a generic back icon
                                            back_btn = page.locator("button[aria-label='Close']")
                                        
                                        if await back_btn.is_visible():
                                            await back_btn.click(timeout=3000)
                                            print(f"[{name}] Closed community tab (Go back to Chat).")
                                        else:
                                            # If we can't find a back button, maybe the community button IS a toggle?
                                            # But user said it disappears. Let's try to find the community button again just in case.
                                            if await community_btn.is_visible():
                                                await community_btn.click(timeout=3000)
                                                print(f"[{name}] Closed community tab (Toggle).")
                                            else:
                                                print(f"[{name}] Warning: Could not find 'Back to Chat' button to close list.")
                                                
                                    except Exception as e:
                                        print(f"[{name}] Warning: Could not close community tab: {e}")

                            else:
                                print(f"[{name}] Could not find Community button.")
                        except Exception as e:
                            print(f"[{name}] Error checking chat list: {e}")
                    # ----------------------------------------

                except Exception as e:
                    print(f"[{name}] Error processing: {e}")
                    # If critical error, maybe close and retry later
                    try:
                        await page.close()
                    except:
                        pass
                    state["page"] = None
            
            # Wait before next cycle
            await asyncio.sleep(2)

if __name__ == "__main__":
    should_restart = True
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Script stopped by user.")
        should_restart = False
    except Exception as e:
        print(f"Unexpected error: {e}")
        should_restart = False

    if should_restart:
        print("Re-executing script to apply updates...")
        os.execv(sys.executable, [sys.executable] + sys.argv)
