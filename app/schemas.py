from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# Knowledge Entry
class KnowledgeEntryBase(BaseModel):
    title: str
    category: str   # common_questions | explanation_templates | service_policies | operator_notes | update_records
    content: str
    tags: Optional[str] = None
    relevant_for: Optional[str] = None  # e.g. "congestion,delays,accident"

class KnowledgeEntryCreate(KnowledgeEntryBase):
    pass

class KnowledgeEntryUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[str] = None
    relevant_for: Optional[str] = None

class KnowledgeEntryOut(KnowledgeEntryBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# FAQ
class FAQBase(BaseModel):
    question: str
    answer: str
    category: str   # congestion | accident | route_conditions | delays | road_closures | travel_advice

class FAQCreate(FAQBase):
    pass

class FAQUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None

class FAQOut(FAQBase):
    id: int
    match_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Incident
class IncidentBase(BaseModel):
    tomtom_id: Optional[str] = None
    type: str           # accident | construction | event_congestion | weather_disruption | high_traffic_demand | road_blockage
    description: str
    location: str
    location_en: Optional[str] = None
    affected_roads: Optional[str] = None
    severity: str = "medium"    # low | medium | high | critical
    status: str = "active"
    estimated_clearance: Optional[str] = None
    alternate_route: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class IncidentCreate(IncidentBase):
    pass

class IncidentUpdate(BaseModel):
    type: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    affected_roads: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    estimated_clearance: Optional[str] = None
    alternate_route: Optional[str] = None

class IncidentOut(IncidentBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Query
class QueryRequest(BaseModel):
    question: str
    language: Optional[str] = "en"   # "en" or "th"

class RouteSummary(BaseModel):
    travel_time_mins: int
    length_km: float
    traffic_delay_mins: int

class QueryResponse(BaseModel):
    answer: str
    intent: Optional[str] = None
    used_live_data: bool = False
    sources: Optional[List[str]] = []
    focus_lat: Optional[float] = None
    focus_lng: Optional[float] = None
    route_points: Optional[List[List[float]]] = None   # [[lat, lng], ...]
    route_summary: Optional[RouteSummary] = None
    suggested_roads: Optional[List[str]] = None        # congested road chips
