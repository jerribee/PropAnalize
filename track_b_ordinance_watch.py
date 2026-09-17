"""
Track B — ordinance change detection.

Unlike Track A, this script never overwrites the live dimensional-standards
table by itself. Zoning setbacks and coverage limits are written by human
city councils and carry real legal weight, so the automation's job here is
narrower and more honest: notice that *something* changed on a town's code
page, and put it in front of a person before it affects what the product
tells anyone.

Approach: rather than guessing at each platform's exact HTML structure
(brittle, and I haven't verified the live markup for every town), this
hashes the visible text of each town's code/"New Laws" page and compares it
month over month. A changed hash doesn't prove the zoning chapter changed —
it proves *something* on that page changed — so a human (or a follow-up
LLM pass reading the diff) still confirms relevance before anything is
trusted. That's a deliberate trade: fewer false negatives, some false
positives, and nothing ever silently goes stale OR silently goes live.

Run monthly, same cadence as Track A:
    python3 track_b_ordinance_watch.py
"""

import hashlib
import json
import os
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import TOWNS, STATE_DIR

REQUEST_TIMEOUT = 20
REVIEW_QUEUE_PATH = os.path.join(STATE_DIR, "ordinance_review_queue.json")


def fetch_visible_text(url: str) -> str | None:
    """Fetch a page and return its visible text, stripped of scripts/styles/nav noise."""
    try:
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "PropertyIntelligenceBot/0.1"}
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  ! could not fetch {url}: {exc}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return text


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_state(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def load_review_queue() -> list:
    if os.path.exists(REVIEW_QUEUE_PATH):
        with open(REVIEW_QUEUE_PATH, "r") as f:
            return json.load(f)
    return []


def save_review_queue(queue: list) -> None:
    with open(REVIEW_QUEUE_PATH, "w") as f:
        json.dump(queue, f, indent=2)


def check_town(town: dict) -> None:
    name = town["name"]
    url = town["code_url"]
    print(f"Checking {name} ({town['platform']}) — {url}")

    if town["platform"] == "pdf":
        # Towns with only a static PDF and no change-feed at all. Same
        # hash-diff approach, just against the PDF's raw bytes rather than
        # rendered page text — cruder, but it's the honest ceiling for a
        # source with no structured "what changed" signal of its own.
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            current_hash = hashlib.sha256(resp.content).hexdigest()
        except requests.RequestException as exc:
            print(f"  ! could not fetch PDF for {name}: {exc}")
            return
    else:
        text = fetch_visible_text(url)
        if text is None:
            return
        current_hash = hash_text(text)

    state_path = os.path.join(STATE_DIR, f"ordinance_{name.lower().replace(' ', '_')}.json")
    previous = load_state(state_path)
    previous_hash = previous.get("hash")

    checked_at = datetime.now(timezone.utc).isoformat()

    if previous_hash is None:
        print(f"  \u2192 first run for {name}, storing baseline")
    elif previous_hash != current_hash:
        print(f"  \u26a0 CHANGE DETECTED on {name}'s code page — queued for review")
        queue = load_review_queue()
        queue.append(
            {
                "town": name,
                "url": url,
                "detected_at": checked_at,
                "status": "pending_review",
                "note": (
                    "Page content changed since last check. Confirm whether "
                    "this touches the zoning/dimensional-standards chapter "
                    f"({town.get('zoning_title', 'zoning title unknown')}) "
                    "before updating the live table."
                ),
            }
        )
        save_review_queue(queue)
    else:
        print(f"  \u2713 no change since last check")

    with open(state_path, "w") as f:
        json.dump({"hash": current_hash, "checked_at": checked_at}, f, indent=2)


def main() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    for town in TOWNS:
        check_town(town)

    queue = load_review_queue()
    pending = [item for item in queue if item["status"] == "pending_review"]
    if pending:
        print(f"\n{len(pending)} item(s) awaiting human review in {REVIEW_QUEUE_PATH}")


if __name__ == "__main__":
    main()
