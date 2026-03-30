import re
from datetime import datetime, timezone
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
    calculate_route_arrive_at,
)
from app.services.flow_sync import format_all_roads_flow, find_road_by_query, get_congested_roads
from app.models import QueryLog, Incident, TravelTimeLog
from typing import Optional

# ── Route query helpers ────────────────────────────────────────────────────────

_ROUTE_RE = re.compile(
    r'from\s+(.+?)\s+to\s+(.+?)(?:\s+avoiding\s+(.+?))?(?:\s*[?!.])?$',
    re.IGNORECASE,
)

# Matches "route to X", "directions to X", "navigate to X", "take me to X",
# "what abt to X", "what about to X", "get to X", "going to X", "head to X", "travel to X"
_ROUTE_TO_RE = re.compile(
    r'(?:route|directions?|navigate|take me|go|get|going|head|travel|what\s+a(?:bt|bout)|how\s+(?:long|far|do\s+i\s+get))\s+to\s+(.+?)(?:\s+avoiding\s+(.+?))?(?:\s*[?!.])?$',
    re.IGNORECASE,
)

_SUGGESTION_KWS = [
    "best route to avoid", "route to avoid congestion",
    "avoid congestion", "which roads are congested",
    "most congested roads", "congested roads right now",
]

def _extract_route(question: str):
    """Return (origin, destination, avoid_road) or (None, None, None).
    origin may be None if only destination is specified (user location will be used)."""
    clean = re.sub(r'^(?:best\s+)?route\s+', '', question, flags=re.IGNORECASE).strip()

    # Try "from X to Y [avoiding Z]"
    m = _ROUTE_RE.search(clean)
    if m:
        origin = m.group(1).strip().rstrip('?.,!')
        dest   = m.group(2).strip().rstrip('?.,!')
        avoid  = m.group(3).strip().rstrip('?.,!') if m.group(3) else None
        if '[' not in origin and '[' not in dest:
            return origin, dest, avoid

    # Try "route to X [avoiding Z]" (no origin — use user location)
    m2 = _ROUTE_TO_RE.search(question)
    if m2:
        dest  = m2.group(1).strip().rstrip('?.,!')
        avoid = m2.group(2).strip().rstrip('?.,!') if m2.group(2) else None
        if '[' not in dest:
            return None, dest, avoid

    return None, None, None

def _is_suggestion_query(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in _SUGGESTION_KWS)

# ── "When should I leave" detection ───────────────────────────────────────────

# Detects departure/arrival planning intent
_LEAVE_INTENT_RE = re.compile(
    r'(?:what time|when)\s+should\s+i\s+(?:leave|go|depart|head\s+out)'
    r'|how\s+(?:long|early)\s+(?:do\s+i\s+need|should\s+i\s+(?:leave|go|depart))'
    r'|what\s+time\s+(?:do\s+i\s+(?:need\s+to\s+)?(?:leave|go|depart))'
    r'|when\s+(?:do\s+i\s+(?:need\s+to\s+)?(?:leave|go|depart))',
    re.IGNORECASE,
)
# Extracts destination — looks for "to/for <place>" anywhere in question
_LEAVE_DEST_RE = re.compile(
    r'(?:to|for)\s+([A-Za-z0-9\s]+?)(?:\s+(?:if|so|to\s+arrive|to\s+reach|to\s+get|by\s+\d|so\s+that)|\?|$)',
    re.IGNORECASE,
)
# Extracts arrival time — "by 9", "by 9am", "arrive by 9:30 pm"
_LEAVE_TIME_RE = re.compile(r'(?:by|arrive\s+by|reach\s+by|get\s+there\s+by)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)', re.IGNORECASE)

_TIME_RE = re.compile(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', re.IGNORECASE)

def _parse_arrival_hour(time_str: str) -> Optional[int]:
    """Parse '6 pm', '6:00 pm', '18:00' → hour (0-23)."""
    m = _TIME_RE.search(time_str.strip())
    if not m:
        return None
    hour = int(m.group(1))
    meridiem = (m.group(3) or '').lower()
    if meridiem == 'pm' and hour != 12:
        hour += 12
    elif meridiem == 'am' and hour == 12:
        hour = 0
    return hour % 24

def _get_historical_avg(db: Session, dest_name: str, dest_lat: float, dest_lng: float, day_of_week: int, arrival_hour: int) -> Optional[float]:
    """Return average travel time from last 4 matching records."""
    # Match by name OR by proximity (within ~1km)
    lat_range = 0.009  # ~1km
    lng_range = 0.009
    hour_window = 2   # ±2 hours around arrival time

    records = (
        db.query(TravelTimeLog)
        .filter(
            TravelTimeLog.day_of_week == day_of_week,
            TravelTimeLog.hour.between(arrival_hour - hour_window, arrival_hour + hour_window),
            (
                (TravelTimeLog.dest_name == dest_name.lower().strip()) |
                (
                    TravelTimeLog.dest_lat.between(dest_lat - lat_range, dest_lat + lat_range) &
                    TravelTimeLog.dest_lng.between(dest_lng - lng_range, dest_lng + lng_range)
                )
            )
        )
        .order_by(TravelTimeLog.created_at.desc())
        .limit(4)
        .all()
    )

    if not records:
        return None
    return sum(r.travel_time_mins for r in records) / len(records)

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
    # ── 0. "When should I leave for X to arrive by Y?" ────────────────────────
    intent_match = _LEAVE_INTENT_RE.search(request.question)
    dest_match   = _LEAVE_DEST_RE.search(request.question)
    time_match   = _LEAVE_TIME_RE.search(request.question)
    print(f"[leave] intent={bool(intent_match)} dest={dest_match and dest_match.group(1)} time={time_match and time_match.group(1)}")
    if intent_match and dest_match and time_match:
        dest_name    = dest_match.group(1).strip().rstrip('?.,! ')
        time_str     = time_match.group(1).strip()
        arrival_hour = _parse_arrival_hour(time_str)
    else:
        intent_match = None
    if intent_match and arrival_hour is not None:
        lang = request.language or "en"
        dest_lat, dest_lng = await geocode_place(dest_name)

        route_points = None; route_summary = None; focus_lat = None; focus_lng = None
        if not dest_lat:
            answer = f"I couldn't find '{dest_name}' in Bangkok. Try a more specific name."
        elif not lat or not lon:
            answer = (
                f"Enable your location on the Map page so I can calculate travel time to {dest_name}."
                if lang != "th" else
                f"กรุณาเปิดตำแหน่งของคุณในหน้าแผนที่เพื่อให้ฉันคำนวณเวลาเดินทางไป {dest_name}"
            )
        else:
            from datetime import timedelta
            import pytz
            import asyncio
            bkk_tz = pytz.timezone("Asia/Bangkok")
            now_bkk = datetime.now(bkk_tz)

            # Find the next occurrence of the same weekday at arrival_hour
            target_weekday = now_bkk.weekday()
            base_dt = now_bkk.replace(hour=arrival_hour, minute=0, second=0, microsecond=0)
            if base_dt <= now_bkk:
                base_dt += timedelta(days=1)
            # Advance to next same weekday
            while base_dt.weekday() != target_weekday:
                base_dt += timedelta(days=1)

            # Build 4 occurrences (same weekday, 1 week apart)
            arrive_dts = [base_dt + timedelta(weeks=i) for i in range(4)]
            day_name = base_dt.strftime("%A")
            arrive_str = f"{arrival_hour % 12 or 12}:00 {'AM' if arrival_hour < 12 else 'PM'}"

            # Call TomTom arriveAt for all 4 in parallel
            tasks = [
                calculate_route_arrive_at(lat, lon, dest_lat, dest_lng, dt.strftime("%Y-%m-%dT%H:%M:%S"))
                for dt in arrive_dts
            ]
            results = await asyncio.gather(*tasks)
            valid = [r for r in results if r is not None]

            if valid:
                avg_mins = round(sum(r["travel_time_mins"] for r in valid) / len(valid))
                avg_km   = round(sum(r["length_km"] for r in valid) / len(valid), 1)
                depart_total = arrival_hour * 60 - avg_mins
                depart_h = depart_total // 60
                depart_m = depart_total % 60
                depart_str = f"{depart_h % 12 or 12}:{depart_m:02d} {'AM' if depart_h < 12 else 'PM'}"

                if lang == "th":
                    answer = (
                        f"จากการวิเคราะห์รูปแบบจราจรของวัน{day_name}ช่วง {arrive_str} "
                        f"จำนวน {len(valid)} สัปดาห์ถัดไป "
                        f"คาดว่าจะใช้เวลาเดินทางไป {dest_name} เฉลี่ย {avg_mins} นาที ({avg_km} กม.) "
                        f"เพื่อถึงให้ทันเวลา {arrive_str} ควรออกเดินทางเวลา {depart_str}"
                    )
                else:
                    answer = (
                        f"Predicted travel time to {dest_name} on {day_name}s around {arrive_str}: "
                        f"**{avg_mins} minutes** ({avg_km} km) — averaged across {len(valid)} upcoming {day_name}s "
                        f"using TomTom's traffic model.\n\n"
                        f"To arrive by {arrive_str}, leave at **{depart_str}**."
                    )
                route_points = valid[0].get("route_points")
                route_summary = {"travel_time_mins": avg_mins, "length_km": avg_km, "traffic_delay_mins": 0}
                mid_idx = len(route_points) // 2 if route_points else 0
                focus_lat = route_points[mid_idx][0] if route_points else dest_lat
                focus_lng = route_points[mid_idx][1] if route_points else dest_lng
            else:
                answer = f"I couldn't calculate a route to {dest_name} right now. Please try again."
                route_points = None
                route_summary = None
                focus_lat = dest_lat
                focus_lng = dest_lng

        log = QueryLog(user_query=request.question, intent="travel_advice", response=answer, used_live_data="true")
        db.add(log); db.commit()
        return QueryResponse(
            answer=answer, intent="travel_advice", used_live_data=True, sources=[],
            route_points=route_points,
            route_summary=route_summary,
            focus_lat=focus_lat,
            focus_lng=focus_lng,
        )

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

    # ── 2. Actual route query: "Route from X to Y" or "Route to Y" ──────────
    origin, destination, avoid_road = _extract_route(request.question)
    if destination:
        # Use user's GPS as origin if no origin place was specified
        if origin is None and lat and lon:
            from_lat, from_lon = lat, lon
            origin = "Your location"
        elif origin:
            from_lat, from_lon = await geocode_place(origin)
        else:
            from_lat, from_lon = None, None

        to_lat, to_lon = await geocode_place(destination)

        if not from_lat or not to_lat:
            if not from_lat and origin == "Your location":
                answer = "I need your location to route from here. Please tap 'Use My Location' on the Map page first."
            else:
                failed = origin if not from_lat else destination
                answer = (
                    f"I couldn't locate '{failed}' in Bangkok. "
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

        # Log travel time for historical predictions
        now = datetime.now(timezone.utc)
        tlog = TravelTimeLog(
            dest_name=destination.lower().strip(),
            dest_lat=to_lat, dest_lng=to_lon,
            day_of_week=now.weekday(), hour=now.hour,
            travel_time_mins=route_summary["travel_time_mins"],
        )
        db.add(tlog)

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
                # Flag that the specific road in the query wasn't found
                request.question = request.question + "\n\n[SYSTEM NOTE: The road/location mentioned above was NOT found in the Bangkok traffic database. Do not use any road name from the user's question. If asked about a specific road, say it was not found in the system.]"

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
