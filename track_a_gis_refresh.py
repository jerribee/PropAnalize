"""
Track A — GIS layer refresh.

Re-queries RIGIS's statewide parcel, flood zone, and wetland jurisdiction
layers for every tracked property and overwrites the stored result. This is
safe to run fully automatically and unattended: the source is the state's
own authoritative GIS, so there's no "is this actually true" judgment call
being made here the way there is with ordinance text (see Track B).

Run monthly via cron / GitHub Actions / a serverless scheduler:
    python3 track_a_gis_refresh.py
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

from config import RIGIS_LAYERS, PROPERTIES, STATE_DIR

REQUEST_TIMEOUT = 15  # seconds


def query_layer(service_url: str, layer_id: int, lat: float, lng: float) -> dict | None:
    """
    Point-in-polygon query against one ArcGIS REST feature layer.

    Sends the point as WGS84 (inSR=4326) and lets the service reproject
    internally — this works regardless of the layer's native spatial
    reference (RIGIS layers are a mix of State Plane feet and Web Mercator),
    so callers never need to handle projection math themselves.
    """
    url = f"{service_url}/{layer_id}/query"
    params = {
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  ! query failed for {url}: {exc}")
        return None

    if "error" in data:
        print(f"  ! service returned an error for {url}: {data['error']}")
        return None

    features = data.get("features", [])
    if not features:
        return None  # point doesn't fall inside any polygon on this layer
    return features[0].get("attributes", {})


def refresh_property(prop: dict) -> dict:
    """Query every configured layer for one property and return a result dict."""
    if prop.get("lat") is None or prop.get("lng") is None:
        print(f"  ! skipping {prop['address']}: no verified coordinates on file")
        return {"address": prop["address"], "status": "skipped_no_coordinates"}

    result = {
        "address": prop["address"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "layers": {},
    }

    for layer_key, layer_cfg in RIGIS_LAYERS.items():
        attrs = query_layer(
            layer_cfg["service_url"], layer_cfg["layer_id"], prop["lat"], prop["lng"]
        )
        result["layers"][layer_key] = {
            "source": layer_cfg["source_label"],
            "found": attrs is not None,
            "attributes": attrs,
        }
    return result


def load_previous_state(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def diff_and_report(address: str, old: dict | None, new: dict) -> None:
    """Print a plain-language summary of what changed, if anything."""
    if old is None:
        print(f"  \u2192 first run for {address}, nothing to compare against")
        return
    for layer_key, new_layer in new["layers"].items():
        old_layer = old.get("layers", {}).get(layer_key, {})
        if old_layer.get("attributes") != new_layer.get("attributes"):
            print(f"  \u26a0 CHANGE DETECTED on {layer_key} for {address}")
            print(f"      was: {old_layer.get('attributes')}")
            print(f"      now: {new_layer.get('attributes')}")


def main() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    any_failures = False

    for prop in PROPERTIES:
        print(f"Refreshing {prop['address']}...")
        state_path = os.path.join(STATE_DIR, f"gis_{prop['parcel_id']}.json")
        previous = load_previous_state(state_path)

        current = refresh_property(prop)
        if current.get("status") == "skipped_no_coordinates":
            any_failures = True
            continue

        diff_and_report(prop["address"], previous or None, current)

        with open(state_path, "w") as f:
            json.dump(current, f, indent=2)
        print(f"  \u2713 saved {state_path}")

    if any_failures:
        sys.exit(1)  # non-zero exit lets a CI/cron runner flag the run as needing attention


if __name__ == "__main__":
    main()
