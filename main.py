"""
Property Intelligence API.

One real endpoint: GET /api/property?address=...

Given a free-text address, this:
  1. Geocodes it via the U.S. Census Bureau's free geocoder (no API key).
  2. Runs a point-in-polygon query against each configured RIGIS layer
     (flood zone, wetland jurisdiction, parcel) for that point.
  3. Returns one JSON object the dashboard can render directly, with each
     fact tagged by source and a "confirmed" flag — mirroring the product's
     core rule of never asserting something it hasn't verified.

Run locally:
    pip install -r requirements.txt
    uvicorn api.main:app --reload
Then visit:
    http://127.0.0.1:8000/api/property?address=2+Dwight+St,+Cranston,+RI+02921
    http://127.0.0.1:8000/docs   (interactive API docs, free from FastAPI)

Note: this has not been executed against the live Census/RIGIS services from
inside this sandbox (outbound network here is restricted to package
registries) — the endpoints and field names are the same ones confirmed via
search/fetch during design, but test this in your own environment before
pointing a real dashboard at it.
"""

from __future__ import annotations

import time
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import RIGIS_LAYERS

app = FastAPI(
    title="Property Intelligence API",
    description="Geocode + statewide RI GIS lookups for a single address.",
    version="0.1.0",
)

# Allow the published dashboard (or a local dev server) to call this API from
# the browser. Lock this down to your actual dashboard's domain once deployed
# — "*" is fine for local development, not for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
REQUEST_TIMEOUT = 15

# Extremely simple in-memory cache so repeated lookups of the same address
# within one process don't re-hit Census/RIGIS every time. Swap for a real
# cache (Redis) or the database itself once this runs as more than one
# process — an in-memory dict disappears on every restart/redeploy and isn't
# shared across serverless instances.
_cache: dict[str, dict] = {}
CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # one week; GIS boundaries don't move often


class Coordinates(BaseModel):
    lat: float
    lng: float
    matched_address: str


class LayerResult(BaseModel):
    source: str
    confirmed: bool
    attributes: Optional[dict] = None


class PropertyResponse(BaseModel):
    input_address: str
    coordinates: Coordinates
    layers: dict[str, LayerResult]
    checked_at: float


def geocode_address(address: str) -> Coordinates:
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "format": "json",
    }
    try:
        resp = requests.get(CENSUS_GEOCODER_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Geocoder request failed: {exc}") from exc

    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        raise HTTPException(
            status_code=404,
            detail="Could not geocode that address — check spelling, or it may not be in the Census's address range data.",
        )

    best = matches[0]
    coords = best["coordinates"]
    return Coordinates(
        lat=coords["y"],
        lng=coords["x"],
        matched_address=best["matchedAddress"],
    )


def query_layer(service_url: str, layer_id: int, lat: float, lng: float) -> Optional[dict]:
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
    except (requests.RequestException, ValueError):
        return None  # a failed layer query degrades to "not confirmed", not a crash

    if "error" in data:
        return None

    features = data.get("features", [])
    if not features:
        return None
    return features[0].get("attributes", {})


@app.get("/api/property", response_model=PropertyResponse)
def get_property(
    address: str = Query(..., description="Full street address, e.g. '2 Dwight St, Cranston, RI 02921'")
):
    cache_key = address.strip().lower()
    cached = _cache.get(cache_key)
    if cached and (time.time() - cached["checked_at"]) < CACHE_TTL_SECONDS:
        return cached["response"]

    coords = geocode_address(address)

    layers: dict[str, LayerResult] = {}
    for layer_key, layer_cfg in RIGIS_LAYERS.items():
        attrs = query_layer(layer_cfg["service_url"], layer_cfg["layer_id"], coords.lat, coords.lng)
        layers[layer_key] = LayerResult(
            source=layer_cfg["source_label"],
            confirmed=attrs is not None,
            attributes=attrs,
        )

    response = PropertyResponse(
        input_address=address,
        coordinates=coords,
        layers=layers,
        checked_at=time.time(),
    )

    _cache[cache_key] = {"response": response, "checked_at": time.time()}
    return response


@app.get("/api/health")
def health():
    """Plain liveness check for uptime monitoring."""
    return {"status": "ok"}
