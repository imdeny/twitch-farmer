# Twitch Farmer

A Python script to automate watching Twitch streams to farm channel points.

## Setup

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configuration**:
    - Copy `env.example` to a new file named `.env`:
        ```bash
        cp env.example .env
        ```
    - Edit `.env` and add your configuration:
        - `MY_USERNAME`: Your Twitch username (used to check if you are in the chat list).
        - `CHANNELS`: A comma-separated list of Twitch channels to monitor.
        - `HEADLESS`: Set to `True` to run the browser in headless mode (default: `False`).
        - `LOG_LEVEL`: Set logging level (e.g., `INFO`, `DEBUG`; default: `INFO`).

3.  **Run**:
    ```bash
    python collector.py
    ```

## Features

-   **Auto-Restart**: Automatically restarts every 4 hours to refresh channel lists.
-   **Offline Detection**: Closes tabs for offline channels and retries later.
-   **Raid Detection**: Detects if a channel raids another and closes the tab.
-   **Bonus Collection**: Automatically clicks the "Claim Bonus" chest.
-   **Chat List Check**: Verifies if your user is present in the chat list.
