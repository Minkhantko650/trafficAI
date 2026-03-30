import re
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import QueryRequest, QueryResponse
from app.services.openai_service import generate_answer
from app.services.traffic_service import (
    get_traffic_incidents,
    get_traffic_flow,
    format_incidents_for_context,
    format_flow_for_context,
    get_first_incident_coords,
    geocode_road,
    geocode_place,
    calculate_route,
)
from app.services.flow_sync import format_all_roads_flow, find_road_by_query, get_congested_roads
from app.models import QueryLog, Incident
from typing import Optional

# ── Route query helpers ────────────────────────────────────────────────────────

_ROUTE_RE = re.compile(
    r'from\s+(.+?)\s+to\s+(.+?)(?:\s+avoiding\s+(.+?))?(?:\s*[?!.])?$',
    re.IGNORECASE,
)

_SUGGESTION_KWS = [
    "best route to avoid", "route to avoid congestion",
    "avoid congestion", "which roads are congested",
    "most congested roads", "congested roads right now",
]

def _extract_route(question: str):
    """Return (origin, destination, avoid_road) or (None, None, None)."""
    # Strip leading "route" / "best route" so regex works on the rest
    clean = re.sub(r'^(?:best\s+)?route\s+', '', question, flags=re.IGNORECASE).strip()
    m = _ROUTE_RE.search(clean)
    if not m:
        return None, None, None
    origin = m.group(1).strip().rstrip('?.,!')
    dest   = m.group(2).strip().rstrip('?.,!')
    avoid  = m.group(3).strip().rstrip('?.,!') if m.group(3) else None
    # Reject unfilled template placeholders
    if '[' in origin or '[' in dest:
        return None, None, None
    return origin, dest, avoid

def _is_suggestion_query(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in _SUGGESTION_KWS)

router = APIRouter(prefix="/query", tags=["Query"])

# Default Bangkok center
DEFAULT_LAT = 13.7563
DEFAULT_LON = 100.5018

@router.post("/", response_model=QueryResponse)
async def query_traffic(
    request: QueryRequest,
    lat: Optional[float] = Query(default=None, description="Latitude for live traffic lookup"),
    lon: Optional[float] = Query(default=None, description="Longitude for live traffic lookup"),
    db: Session = Depends(get_db)
):
    # ── 1. Route suggestion: "Best route to avoid congestion?" ────────────────
    if _is_suggestion_query(request.question):
        congested = get_congested_roads()
        suggested = [r["name"] for r in congested[:6]]
        if suggested:
            roads_str = ", ".join(f"{r['name']} ({r['congestion']})" for r in congested[:5])
            if (request.language or "en") == "th":
                answer = (
                    f"ถนนที่มีการจราจรติดขัดขณะนี้: {roads_str} "
                    "แตะชื่อถนนด้านล่างเพื่อวางแผนเส้นทาง หรือพิมพ์ "
                    "'เส้นทางจาก [ต้นทาง] ถึง [ปลายทาง] หลีกเลี่ยง [ชื่อถนน]'"
                )
            else:
                answer = (
                    f"Here are the most congested roads right now: {roads_str}. "
                    "Tap a road below to plan your route around it, or type "
                    "'Route from [origin] to [destination] avoiding [road name]'."
                )
        else:
            answer = (
                "All major Bangkok roads are flowing freely right now — no significant congestion detected."
                if (request.language or "en") != "th"
                else "ขณะนี้ถนนสายหลักในกรุงเทพฯ ไม่มีการจราจรติดขัดที่มีนัยสำคัญ"
            )
        log = QueryLog(
            user_query=request.question, intent="route_conditions",
            response=answer, used_live_data="true"
        )
        db.add(log); db.commit()
        return QueryResponse(
            answer=answer, intent="route_conditions",
            used_live_data=True, sources=[],
            suggested_roads=suggested if suggested else None,
        )

    # ── 2. Actual route query: "Route from X to Y [avoiding Z]" ──────────────
    origin, destination, avoid_road = _extract_route(request.question)
    if origin and destination:
        from_lat, from_lon = await geocode_place(origin)
        to_lat,   to_lon   = await geocode_place(destination)

        if not from_lat or not to_lat:
            answer = (
                f"I couldn't locate '{origin if not from_lat else destination}' in Bangkok. "
                "Please use a more specific place name (e.g. 'Siam BTS', 'Central World', 'On Nut')."
            )
            return QueryResponse(answer=answer, intent="route_conditions", used_live_data=False)

        avoid_lat = avoid_lon = None
        avoid_road_name = None
        if avoid_road:
            rname, rcoords = find_road_by_query(avoid_road)
            if rcoords:
                avoid_lat, avoid_lon = rcoords["lat"], rcoords["lon"]
                avoid_road_name = rname.replace(" Bangkok", "") if rname else avoid_road

        route_points, route_summary = await calculate_route(
            from_lat, from_lon, to_lat, to_lon, avoid_lat, avoid_lon
        )

        if not route_points:
            return QueryResponse(
                answer="Sorry, I couldn't calculate a route right now. Please try again.",
                intent="route_conditions", used_live_data=False,
            )

        avoid_note = f"Avoiding: {avoid_road_name}" if avoid_road_name else "Using live traffic (fastest route)"
        route_context = (
            f"Route: {origin} → {destination}\n"
            f"Distance: {route_summary['length_km']} km\n"
            f"Travel time: {route_summary['travel_time_mins']} minutes\n"
            f"Traffic delay: {route_summary['traffic_delay_mins']} minutes\n"
            f"{avoid_note}"
        )

        # Minimal live data for GPT context
        try:
            mid = len(route_points) // 2
            inc_data = await get_traffic_incidents(route_points[mid][0], route_points[mid][1])
        except Exception:
            inc_data = {"incidents": []}
        live_inc = format_incidents_for_context(inc_data)

        result = await generate_answer(
            query=request.question, db=db,
            live_incidents=live_inc, live_flow="",
            language=request.language or "en",
            route_context=route_context,
        )

        log = QueryLog(
            user_query=request.question, intent="route_conditions",
            response=result["answer"], used_live_data="true"
        )
        db.add(log); db.commit()

        mid_idx = len(route_points) // 2
        return QueryResponse(
            answer=result["answer"],
            intent="route_conditions",
            used_live_data=True,
            sources=[],
            focus_lat=route_points[mid_idx][0],
            focus_lng=route_points[mid_idx][1],
            route_points=route_points,
            route_summary=route_summary,
        )

    # ── 3. Normal traffic query ────────────────────────────────────────────────
    is_generic = False
    matched_road_name = None
    matched_road_coords = None
    if not lat or not lon:
        # Priority: check flow_sync known roads first (exact names + cached coords)
        matched_road_name, matched_road_coords = find_road_by_query(request.question)
        if matched_road_name and matched_road_coords:
            lat = matched_road_coords["lat"]
            lon = matched_road_coords["lon"]
            print(f"[query] Matched flow_sync road: {matched_road_name} → ({lat}, {lon})")
        else:
            geo_lat, geo_lon = await geocode_road(request.question)
            if geo_lat and geo_lon:
                lat, lon = geo_lat, geo_lon
                print(f"[query] Geocoded '{request.question}' → ({lat}, {lon})")
            else:
                lat, lon = DEFAULT_LAT, DEFAULT_LON
                is_generic = True
                print(f"[query] No road found in query, using all-roads overview")

    try:
        incidents_data = await get_traffic_incidents(lat, lon)
    except Exception:
        incidents_data = {"incidents": []}
    try:
        flow_data = await get_traffic_flow(lat, lon)
    except Exception:
        flow_data = {}
    live_incidents_text = format_incidents_for_context(incidents_data)

    # For generic queries, replace single-point flow with all major roads overview
    if is_generic:
        all_roads = format_all_roads_flow()
        live_flow_text = f"Current traffic on major Bangkok roads:\n{all_roads}"
    else:
        live_flow_text = format_flow_for_context(flow_data)

    result = await generate_answer(
        query=request.question,
        db=db,
        live_incidents=live_incidents_text,
        live_flow=live_flow_text,
        language=request.language or "en"
    )

    log = QueryLog(
        user_query=request.question,
        intent=result["intent"],
        response=result["answer"],
        used_live_data=str(result["used_live"]).lower()
    )
    db.add(log)
    db.commit()

    # Priority 1: if query matched a known road in flow_sync, use that road's exact dot position
    # This ensures "View on Map" always flies to the road's dot on the map
    if matched_road_coords:
        focus_lat = matched_road_coords["lat"]
        focus_lng = matched_road_coords["lon"]
    else:
        focus_lat = None
        focus_lng = None

    # Priority 2: no known road matched — use the most severe live incident TomTom returned
    if not focus_lat:
        focus_lat, focus_lng = get_first_incident_coords(incidents_data)

    # Priority 3: still nothing — use DB incident nearest to the geocoded point
    if not focus_lat:
        nearby = (
            db.query(Incident)
            .filter(
                Incident.status == "active",
                Incident.latitude.isnot(None),
                Incident.longitude.isnot(None),
                Incident.latitude.between(lat - 0.05, lat + 0.05),
                Incident.longitude.between(lon - 0.05, lon + 0.05),
            )
            .order_by(Incident.severity.desc(), Incident.created_at.desc())
            .first()
        )
        if nearby:
            focus_lat = nearby.latitude
            focus_lng = nearby.longitude

    # Priority 4: fall back to the geocoded road center
    if not focus_lat and lat != DEFAULT_LAT:
        focus_lat = lat
        focus_lng = lon

    return QueryResponse(
        answer=result["answer"],
        intent=result["intent"],
        used_live_data=result["used_live"],
        sources=[],
        focus_lat=focus_lat,
        focus_lng=focus_lng,
    )
