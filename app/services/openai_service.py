from openai import OpenAI
from app.config import settings
from sqlalchemy.orm import Session
from app.models import KnowledgeEntry, FAQ, Incident

client = OpenAI(api_key=settings.OPENAI_API_KEY)

# From spec section 12a — 6 question categories + general
# Improved: broader keyword coverage, traffic-related terms added to congestion
INTENT_MAP = {
    "congestion": [
        # English
        "congestion", "heavy", "traffic", "slow", "jam", "busy",
        "backed up", "gridlock", "how is traffic", "bad traffic",
        "rush hour", "peak", "crowded", "moving", "flowing",
        # Thai
        "รถติด", "การจราจร", "ติดขัด", "หนาแน่น", "ชั่วโมงเร่งด่วน",
        "รถหนาแน่น", "ถนนติด", "รถมาก"
    ],
    "accident": [
        # English
        "accident", "crash", "collision", "incident", "hit",
        "vehicle", "emergency", "injured", "overturned", "pile up",
        # Thai
        "อุบัติเหตุ", "รถชน", "ชนกัน", "เฉี่ยวชน", "รถคว่ำ",
        "บาดเจ็บ", "เจ็บ", "ชน"
    ],
    "route_conditions": [
        # English
        "route", "road condition", "road quality", "path",
        "which way", "way to go", "how do i get", "directions",
        # Thai
        "เส้นทาง", "สภาพถนน", "ไปทางไหน", "เดินทาง",
        "ถนน", "ทาง", "เส้น"
    ],
    "delays": [
        # English
        "delay", "wait", "how long", "late", "duration",
        "ETA", "estimated time", "minutes", "hours", "stuck",
        # Thai
        "ล่าช้า", "รอ", "นานแค่ไหน", "ใช้เวลา", "กี่นาที",
        "กี่ชั่วโมง", "ติดนาน", "รอนาน"
    ],
    "road_closures": [
        # English
        "closure", "closed", "blocked", "shutdown",
        "detour", "diversion", "open", "reopen",
        # Thai
        "ปิดถนน", "ถนนปิด", "บล็อค", "เบี่ยงทาง",
        "ทางเลี่ยง", "เปิดถนน", "ปิด"
    ],
    "travel_advice": [
        # English
        "should i", "advice", "recommend", "better", "avoid",
        "best time", "when to travel", "worth", "safer", "faster",
        # Thai
        "ควรไป", "แนะนำ", "เวลาไหนดี", "หลีกเลี่ยง",
        "ดีกว่า", "ปลอดภัย", "เร็วกว่า", "ควร"
    ],
}

def detect_intent(query: str) -> str:
    query_lower = query.lower()
    # Score each intent by number of keyword matches
    scores = {}
    for intent, keywords in INTENT_MAP.items():
        scores[intent] = sum(1 for kw in keywords if kw in query_lower)
    best_intent = max(scores, key=scores.get)
    # Only return if at least one keyword matched
    if scores[best_intent] > 0:
        return best_intent
    return "general"

def get_relevant_kb(db: Session, query: str, intent: str) -> str:
    words = query.lower().split()
    kb_results = []

    entries = db.query(KnowledgeEntry).all()
    for entry in entries:
        searchable = f"{entry.title} {entry.content} {entry.tags or ''} {entry.relevant_for or ''}".lower()
        intent_match = entry.relevant_for and intent in entry.relevant_for
        keyword_match = any(word in searchable for word in words)
        if intent_match or keyword_match:
            kb_results.append(f"[Knowledge] {entry.title}: {entry.content}")

    faqs = db.query(FAQ).all()
    for faq in faqs:
        searchable = f"{faq.question} {faq.answer} {faq.category}".lower()
        if faq.category == intent or any(word in searchable for word in words):
            kb_results.append(f"[FAQ] Q: {faq.question}\nA: {faq.answer}")
            faq.match_count = (faq.match_count or 0) + 1
            db.commit()

    return "\n\n".join(kb_results[:6]) if kb_results else "No relevant knowledge base entries found."

def get_active_incidents(db: Session, intent: str) -> str:
    incidents = db.query(Incident).filter(Incident.status == "active").order_by(Incident.created_at.desc()).limit(10).all()
    if not incidents:
        return "No active incidents currently in the system."

    intent_to_type = {
        "accident": "accident",
        "road_closures": "road_blockage",
        "congestion": "high_traffic_demand",
        "travel_advice": "event_congestion",
    }
    priority_type = intent_to_type.get(intent)
    sorted_incidents = sorted(incidents, key=lambda i: i.type == priority_type, reverse=True)

    lines = []
    for inc in sorted_incidents:
        line = f"- [{inc.severity.upper()}] {inc.type} on {inc.location}: {inc.description}"
        if inc.affected_roads:
            line += f" Affected roads: {inc.affected_roads}."
        if inc.estimated_clearance:
            line += f" Estimated clearance: {inc.estimated_clearance}."
        if inc.alternate_route:
            line += f" Use instead: {inc.alternate_route}."
        lines.append(line)

    return "\n".join(lines)

def _get_answer_instruction(intent: str, route_instruction: str) -> str:
    if route_instruction:
        return route_instruction.strip()
    if intent == "accident":
        return (
            "List each incident as a bullet point: type, location (if known), severity, and delay. "
            "If no incidents are found, say so clearly. Do NOT use the 3-part structure."
        )
    if intent == "road_closures":
        return (
            "List each closure or blockage as a bullet point: road name, reason, and alternate route if available. "
            "Do NOT use the 3-part structure."
        )
    if intent in ("congestion", "delays"):
        return (
            "List the most congested roads as bullet points with speed and congestion level. "
            "End with one sentence of practical advice."
        )
    return "Answer following the 3-part structure: current condition, specific impact, specific recommendation."

async def generate_answer(
    query: str,
    db: Session,
    live_incidents: str = "",
    live_flow: str = "",
    language: str = "en",
    route_context: str = "",
) -> dict:
    intent = detect_intent(query)
    kb_context = get_relevant_kb(db, query, intent)
    db_incidents = get_active_incidents(db, intent)
    used_live = bool(live_incidents or live_flow)

    lang_instruction = "You MUST respond entirely in Thai. Do not use any English words except proper road names." if language == "th" else "You MUST respond entirely in English."

    system_prompt = f"""You are a traffic information assistant for a web-based traffic support platform in Bangkok, Thailand.
Your role is to help drivers, commuters, and travelers get clear, direct, and useful answers to traffic-related questions.

LANGUAGE RULE — CRITICAL:
{lang_instruction}
Never switch languages mid-response.

You have access to:
- Live traffic flow and incident data from TomTom API
- Operator-reported incidents with severity levels and clearance times
- A structured knowledge base of Bangkok traffic support information
- FAQs maintained by traffic operators

Rules:
- ALWAYS mention the specific road name or location from the live data sections below — NEVER use road names from the user's question unless that exact road name appears in the live data
- ALWAYS give a specific alternate route by name if one is available in the data — never say "consider alternate routes"
- ALWAYS mention the exact delay time in minutes if available
- Mention severity level (low/medium/high/critical) when relevant
- If no live data is available, say so and rely on the knowledge base
- Do not invent road names or locations not present in the data
- When asked about "latest", "recent", or "newest" incidents, mention the first incident in the list first as it is the most recently reported

For SPECIFIC location queries (e.g. "how is traffic on Sukhumvit"):
- Structure: 1. Current condition  2. Specific impact (which road, how long)  3. Specific recommendation
- Answer in 3-5 sentences

For GENERAL/OVERVIEW queries (e.g. "is there traffic right now", "how is traffic in Bangkok"):
- List EVERY road from the live flow data with its current status
- Format each road as a bullet point: "• [Road Name]: [speed] km/h — [congestion level]"
- After the list, give a one-line overall summary
- Do NOT summarize into one generic sentence — show each road individually"""

    route_section = (
        f"\n--- CALCULATED ROUTE (TomTom) ---\n{route_context}\n"
        if route_context else ""
    )

    route_instruction = (
        "\nFor ROUTE queries: describe the route clearly — mention origin, destination, travel time, "
        "distance, traffic delay saved, and which congested road is being avoided. "
        "Be concise and practical. 3-4 sentences max."
        if route_context else ""
    )

    user_prompt = f"""User question: {query}
Detected intent: {intent}

--- LIVE TRAFFIC FLOW (TomTom) ---
{live_flow if live_flow else "Live flow data not available."}

--- LIVE INCIDENTS (TomTom) ---
{live_incidents if live_incidents else "No live incident feed for this query."}
{route_section}
--- OPERATOR-REPORTED INCIDENTS (newest first, last 10) ---
{db_incidents}

--- KNOWLEDGE BASE & FAQs ---
{kb_context}

{_get_answer_instruction(intent, route_instruction)}"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=350,
        temperature=0.2
    )

    answer = response.choices[0].message.content.strip()
    return {"answer": answer, "intent": intent, "used_live": used_live}
