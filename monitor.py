import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

TARGET_URL = "https://festivalpresidente.tuboleta.com.do/"
STATE_FILE = Path("state/page_hash.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# HTML tags that never contain relevant content
_NON_CONTENT_TAGS = frozenset(
    {"script", "style", "noscript", "iframe", "meta", "link", "head"}
)

# Class/ID patterns that indicate dynamic or tracking elements
_DYNAMIC_ATTR_RE = re.compile(
    r"\b("
    r"google|analytics|gtag|gtm|fbq|facebook|pixel|"
    r"hotjar|intercom|drift|zendesk|livechat|hubspot|"
    r"cookie|consent|gdpr|ccpa|"
    r"banner|toast|notification|popup|modal|overlay|"
    r"spinner|loading|cargando|"
    r"cart|carrito|badge|"
    r"countdown|timer|clock|cronometro|counter"
    r")\b",
    re.IGNORECASE,
)

# Text patterns to remove (relative times, HH:MM:SS countdowns)
_DYNAMIC_TEXT_RES = [
    re.compile(
        r"\d+\s*(días?|horas?|minutos?|segundos?)\s*(restantes?|left|ago)",
        re.IGNORECASE,
    ),
    re.compile(r"hace\s+\d+\s*(días?|horas?|minutos?|segundos?)", re.IGNORECASE),
    re.compile(r"\b\d{2}:\d{2}:\d{2}\b"),  # HH:MM:SS countdown clocks
]


def _fetch_page(url: str) -> str:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            java_script_enabled=True,
        )
        page = context.new_page()
        try:
            page.goto(url, timeout=30_000, wait_until="networkidle")
            # Extra pause for lazy-loaded content after networkidle
            page.wait_for_timeout(4_000)
            return page.content()
        except PlaywrightTimeoutError:
            print("ERROR: Page load timed out.", file=sys.stderr)
            raise
        finally:
            browser.close()


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Drop technical/non-content tags
    for tag in soup.find_all(_NON_CONTENT_TAGS):
        tag.decompose()

    # Drop dynamic/tracking elements by id, class, or data-testid.
    # Guard against tags already decomposed as children of a removed parent
    # (decompose() sets attrs=None recursively on all descendants).
    for tag in soup.find_all(True):
        if tag.attrs is None:
            continue
        attrs_text = " ".join(
            filter(
                None,
                [
                    tag.get("id", ""),
                    " ".join(tag.get("class", [])),
                    str(tag.get("data-testid", "")),
                    str(tag.get("data-component", "")),
                ],
            )
        )
        if _DYNAMIC_ATTR_RE.search(attrs_text):
            tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Remove dynamic time-based text
    for pattern in _DYNAMIC_TEXT_RES:
        text = pattern.sub("", text)

    # Collapse blank lines and normalize whitespace
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: Could not read state file: {exc}", file=sys.stderr)
        return None


def _save_state(content_hash: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"hash": content_hash}, f, indent=2)
        f.write("\n")


def _send_discord_message(webhook_url: str) -> None:
    payload = {"content": "🚨🚨🚨 Cambio Realizado!"}
    resp = requests.post(webhook_url, json=payload, timeout=10)
    if resp.status_code == 429:
        retry_after = float(resp.json().get("retry_after", 2))
        print(f"Discord rate-limited. Waiting {retry_after}s …", file=sys.stderr)
        time.sleep(retry_after)
        resp = requests.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()


def _send_discord_alert(webhook_url: str) -> None:
    for i in range(1, 4):
        print(f"Sending Discord notification {i}/3 …")
        _send_discord_message(webhook_url)
        if i < 3:
            time.sleep(2)


def main() -> None:
    print(f"Fetching {TARGET_URL} …")
    try:
        html = _fetch_page(TARGET_URL)
    except Exception as exc:
        print(f"ERROR: Could not fetch page: {exc}", file=sys.stderr)
        sys.exit(1)

    content = _clean_html(html)
    current_hash = _compute_hash(content)
    print(f"Content hash: {current_hash}")

    state = _load_state()

    if state is None:
        print("First run — saving initial state. No alert sent.")
        _save_state(current_hash)
        return

    if current_hash == state.get("hash"):
        print("No changes detected.")
        return

    # A real change was found — send alert before saving new state so that
    # a Discord failure on this run causes a retry on the next run.
    print("Change detected — sending Discord alert …")
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print(
            "ERROR: DISCORD_WEBHOOK_URL environment variable is not set.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        _send_discord_alert(webhook_url)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    _save_state(current_hash)
    print("State updated.")


if __name__ == "__main__":
    main()
