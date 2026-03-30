"""Run once to seed the database with Bangkok-specific traffic support data."""
from app.database import SessionLocal, engine, Base
from app.models import KnowledgeEntry, FAQ, Incident

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# ── Knowledge Base ─────────────────────────────────────────────────────────────
# Categories from spec section 12c:
# common_questions | explanation_templates | service_policies | operator_notes | update_records

kb_entries = [
    # --- Explanation Templates ---
    KnowledgeEntry(
        title="Why Bangkok Roads Get Congested During Peak Hours",
        category="explanation_templates",
        content=(
            "Bangkok experiences severe peak-hour congestion between 7:00–9:00 AM and 5:00–8:00 PM on weekdays. "
            "The main causes are high vehicle density, limited road capacity relative to population, and mass entry/exit "
            "of workers in the CBD. Roads like Sukhumvit, Silom, Ratchadaphisek, and Rama IV are most affected. "
            "Using BTS Skytrain, MRT, or traveling outside peak windows reduces delays significantly."
        ),
        tags="peak hour, rush hour, congestion, Bangkok, weekday, morning, evening",
        relevant_for="congestion,delays,travel_advice"
    ),
    KnowledgeEntry(
        title="How Accidents Affect Traffic Flow in Bangkok",
        category="explanation_templates",
        content=(
            "A single-lane accident on a major Bangkok road typically causes 15–30 minute delays. "
            "Multi-vehicle or serious accidents blocking 2+ lanes can cause 1–3 hour disruptions. "
            "Emergency services are dispatched from the nearest highway patrol station. "
            "Traffic is redirected by officers or dynamic signs. Clearance time depends on vehicle removal and investigation."
        ),
        tags="accident, crash, delay, clearance, emergency",
        relevant_for="accident,delays,road_closures"
    ),
    KnowledgeEntry(
        title="Road Closure Procedures and Detour Planning",
        category="service_policies",
        content=(
            "Planned road closures in Bangkok are announced at least 48 hours in advance via official traffic channels. "
            "Expressway Authority of Thailand (EXAT) manages toll road closures. Bangkok Metropolitan Administration (BMA) "
            "handles city road works. Detour signage is placed before closure points. "
            "Emergency closures due to flooding or accidents are announced in real-time via traffic apps and radio."
        ),
        tags="closure, road closed, construction, detour, EXAT, BMA",
        relevant_for="road_closures,travel_advice"
    ),
    KnowledgeEntry(
        title="Weather Impact on Bangkok Traffic",
        category="explanation_templates",
        content=(
            "Heavy rain reduces average traffic speeds by 20–40% in Bangkok due to reduced visibility and flooding risk. "
            "Flash flooding commonly affects low-lying roads in On Nut, Lat Phrao, and Bang Na areas. "
            "During monsoon season (May–October), allow an extra 30–60 minutes for travel. "
            "Flooded roads are closed immediately and alternate elevated routes or expressways are recommended."
        ),
        tags="rain, flood, weather, monsoon, Bangkok, delay",
        relevant_for="delays,travel_advice,road_closures"
    ),
    KnowledgeEntry(
        title="Major Events and Traffic Surge Management",
        category="operator_notes",
        content=(
            "Large events at Rajamangala Stadium, Impact Arena, or MBK Center cause significant traffic surges "
            "within a 3km radius. Traffic control officers are deployed 1 hour before and after events. "
            "Expect 30–60 minute delays in surrounding areas. Public transport (BTS/MRT) is strongly recommended "
            "for event attendance. Parking restrictions are enforced near venues."
        ),
        tags="event, concert, stadium, surge, Bangkok, crowd",
        relevant_for="congestion,travel_advice,delays"
    ),
    KnowledgeEntry(
        title="Best Alternate Routes in Bangkok CBD",
        category="common_questions",
        content=(
            "When Sukhumvit Road is congested: use Asoke-Petchburi Road or Rama IV as parallel alternatives. "
            "When Silom is blocked: use Sathorn Road or the expressway. "
            "When Ratchadaphisek is slow: use the inner city roads via Lat Phrao or Vibhavadi. "
            "The Expressway network (tollway) bypasses most surface congestion but charges tolls of 45–75 THB."
        ),
        tags="alternate route, Sukhumvit, Silom, Ratchadaphisek, expressway, Bangkok",
        relevant_for="route_conditions,travel_advice,congestion"
    ),
]

# ── FAQs ───────────────────────────────────────────────────────────────────────
# Categories from spec section 12a:
# congestion | accident | route_conditions | delays | road_closures | travel_advice

faqs = [
    FAQ(
        question="Why is Sukhumvit Road always congested?",
        answer=(
            "Sukhumvit Road is one of Bangkok's busiest corridors due to high residential and commercial density along its length. "
            "Peak congestion occurs 7–9 AM and 5–8 PM. BTS Skytrain running above it is the fastest alternative during these hours."
        ),
        category="congestion"
    ),
    FAQ(
        question="How long does it take for an accident to clear on a Bangkok expressway?",
        answer=(
            "Minor accidents with no injuries typically clear in 15–30 minutes. "
            "Serious accidents involving injuries or vehicle damage take 1–3 hours. "
            "Expressway patrol teams (EXAT) respond within 10–15 minutes of being notified."
        ),
        category="accident"
    ),
    FAQ(
        question="What is the fastest route from Siam to Asoke during peak hours?",
        answer=(
            "The BTS Sukhumvit Line from Siam to Asoke is the fastest option at approximately 5 minutes. "
            "By road, Rama I to Asoke-Petchburi takes 20–40 minutes during peak hours. "
            "Avoid Sukhumvit Road between 5–8 PM as it is severely congested."
        ),
        category="route_conditions"
    ),
    FAQ(
        question="How long is the delay on Silom Road right now?",
        answer=(
            "Silom Road typically experiences 20–45 minute delays during evening peak hours (5–8 PM). "
            "Check the live traffic feed for current conditions. Sathorn Road is a parallel alternative with generally lighter traffic."
        ),
        category="delays"
    ),
    FAQ(
        question="Is the road to Suvarnabhumi Airport open?",
        answer=(
            "The main access routes to Suvarnabhumi Airport (Highway 7 and Bang Na Expressway) are generally open. "
            "Allow 45–90 minutes from the CBD during peak hours. The Airport Rail Link from Phaya Thai takes 30 minutes and avoids road delays entirely."
        ),
        category="road_closures"
    ),
    FAQ(
        question="When is the best time to travel to avoid Bangkok traffic?",
        answer=(
            "The best travel windows are before 6:30 AM, between 10 AM–3 PM, or after 9 PM. "
            "Avoid weekday peaks (7–9 AM and 5–8 PM) and post-event windows near major venues. "
            "Weekends have lighter traffic but Sunday evenings can be busy near shopping areas."
        ),
        category="travel_advice"
    ),
    FAQ(
        question="How do I report a traffic incident in Bangkok?",
        answer=(
            "Call the Bangkok Traffic Police hotline at 1197, or use the Thai Traffic application. "
            "For expressway incidents, contact EXAT at 1543. Provide your location, type of incident, and number of vehicles involved."
        ),
        category="general"
    ),
]

# ── Incidents ─────────────────────────────────────────────────────────────────
# Types from spec section 12b:
# accident | construction | event_congestion | weather_disruption | high_traffic_demand | road_blockage

incidents = [
    Incident(
        type="accident",
        description="Two-vehicle collision on the left lane. Police and tow truck on scene.",
        location="Sukhumvit Road, between Asoke and Nana intersections",
        affected_roads="Sukhumvit Road",
        severity="high",
        status="active",
        estimated_clearance="45 minutes",
        alternate_route="Use Asoke-Petchburi Road northbound or Rama IV westbound as alternate.",
        latitude=13.7440,
        longitude=100.5601
    ),
    Incident(
        type="construction",
        description="MRT extension construction. Right lane closed with barrier. Flaggers on site.",
        location="Ratchadaphisek Road, Huai Khwang section",
        affected_roads="Ratchadaphisek Road",
        severity="medium",
        status="active",
        estimated_clearance="Ongoing until May 2026",
        alternate_route="Use Lat Phrao Road or Vibhavadi Rangsit Road as parallel routes.",
        latitude=13.7700,
        longitude=100.5695
    ),
    Incident(
        type="high_traffic_demand",
        description="Severe congestion due to peak hour demand. Speeds below 15 km/h across CBD.",
        location="Silom Road and Sathorn Road, Bangkok CBD",
        affected_roads="Silom Road, Sathorn Road",
        severity="high",
        status="active",
        estimated_clearance="Expected to ease after 8:00 PM",
        alternate_route="Use Expressway (Chalerm Mahanakhon) to bypass CBD surface roads.",
        latitude=13.7248,
        longitude=100.5289
    ),
    Incident(
        type="road_blockage",
        description="Flash flooding blocking both lanes. Road impassable for standard vehicles.",
        location="On Nut Road, near Soi On Nut 17",
        affected_roads="On Nut Road",
        severity="critical",
        status="active",
        estimated_clearance="Dependent on rainfall — monitor weather updates",
        alternate_route="Use Sukhumvit Road (elevated sections) or BTS On Nut station for public transport.",
        latitude=13.7012,
        longitude=100.5998
    ),
]

db.add_all(kb_entries)
db.add_all(faqs)
db.add_all(incidents)
db.commit()
db.close()

print("Database seeded with Bangkok-specific traffic data.")
