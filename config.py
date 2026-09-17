"""
Shared configuration for the Property Intelligence data pipeline.

This is deliberately a plain Python file (not a database) for the prototype
stage — swap PROPERTIES and TOWNS for real database tables once this moves
past one demo property. Every URL below was confirmed live via search/fetch
in the design conversation; layer indices marked TODO should be double-
checked against the service's own ?f=pjson listing before relying on them,
since a town or state agency can renumber layers when they republish a
service.
"""

# ---------------------------------------------------------------------------
# TRACK A: statewide GIS services (Rhode Island / RIGIS)
# ---------------------------------------------------------------------------

RIGIS_LAYERS = {
    "flood_zone": {
        "service_url": "https://risegis.ri.gov/hosting/rest/services/RIEMA/RI_Current_Floodplain_Mapping_4_0/MapServer",
        "layer_id": 4,  # "Effective Flood Zones" — confirmed via MapServer/4 listing
        "fields": ["FLD_ZONE", "ZONE_SUBTY", "DFIRM_ID"],
        "source_label": "RIEMA — RI Floodplain Mapping Tool 4.0",
    },
    "wetland_jurisdiction": {
        "service_url": "https://risegis.ri.gov/hosting/rest/services/RIDEM/Boundaries_and_Regulatory_Overlays_v2/MapServer",
        "layer_id": 7,  # "Wetland Jurisdiction" — confirmed via MapServer/7 listing
        "fields": ["AGENCY", "AREA"],
        "source_label": "RIDEM/CRMC — Wetland Jurisdiction",
    },
    "parcel": {
        "service_url": "https://risegis.ri.gov/hosting/rest/services/RIDEM/Tax_Parcels/MapServer",
        "layer_id": 0,  # TODO: confirm the parcel polygon sublayer index via {service_url}?f=pjson
        "fields": ["PLAT", "LOT", "CITY", "TOWN", "AREA_AC"],  # TODO: confirm actual field names on layer 0
        "source_label": "RI State / RIDEM — Statewide Tax Parcels",
    },
}

# Properties this pipeline is currently tracking. In production this is a
# database table (address, lat, lng, parcel_id, plus every field the
# pipeline has previously written), not a hardcoded list.
PROPERTIES = [
    {
        "address": "2 Dwight St, Cranston, RI 02921",
        "town": "Cranston",
        # TODO: replace with a verified geocode (e.g. via the U.S. Census
        # geocoder) before running for real — do not trust a placeholder
        # coordinate the way this tool refuses to trust an unverified
        # zoning district.
        "lat": 41.751743272519,
        "lng": -71.485076369071,
        "parcel_id": "018-1790-000",
    },
]

# ---------------------------------------------------------------------------
# TRACK B: municipal ordinance sources (zoning text, not GIS)
# ---------------------------------------------------------------------------

TOWNS = [
    {
        "name": "Cranston",
        "platform": "ecode360",
        # The specific "New Laws" URL differs per municipality's eCode360
        # subdomain/custId — this is the general code homepage; confirm the
        # New Laws page URL by visiting the code site once and copying it.
        "code_url": "https://ecode360.com/CR1234",  # TODO: replace with Cranston's real eCode360 code URL
        "zoning_title": "Title 17",
    },
    {
        "name": "Warwick",
        "platform": "municode",
        "code_url": "https://library.municode.com/ri/warwick/codes/code_of_ordinances",  # TODO: verify
        "zoning_title": "Zoning",
    },
    # Add one entry per town as coverage expands. Towns on neither platform
    # (a static PDF only) should still get an entry with platform="pdf" —
    # see track_b_ordinance_watch.py's handling for that case.
]

STATE_DIR = "pipeline_state"  # where JSON snapshots are written between runs
