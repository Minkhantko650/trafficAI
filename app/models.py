from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from sqlalchemy.sql import func
from app.database import Base
import enum

# From spec section 12a — Question Categories
class QueryCategory(str, enum.Enum):
    congestion = "congestion"
    accident = "accident"
    route_conditions = "route_conditions"
    delays = "delays"
    road_closures = "road_closures"
    travel_advice = "travel_advice"
    general = "general"

# From spec section 12b — Incident Categories
class IncidentType(str, enum.Enum):
    accident = "accident"
    construction = "construction"
    event_congestion = "event_congestion"
    weather_disruption = "weather_disruption"
    high_traffic_demand = "high_traffic_demand"
    road_blockage = "road_blockage"

# From spec section 12c — Support Content Categories
class KnowledgeCategory(str, enum.Enum):
    common_questions = "common_questions"
    explanation_templates = "explanation_templates"
    service_policies = "service_policies"
    operator_notes = "operator_notes"
    update_records = "update_records"

class SeverityLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"

class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(String(500))
    relevant_for = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class FAQ(Base):
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    category = Column(String(100), nullable=False)
    match_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    tomtom_id = Column(String(255), nullable=True, index=True, unique=False)
    type = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String(255), nullable=False)
    location_en = Column(String(255), nullable=True)
    affected_roads = Column(String(500))
    severity = Column(String(20), nullable=False, default="medium")
    status = Column(String(50), nullable=False, default="active")
    estimated_clearance = Column(String(100))
    alternate_route = Column(Text)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_query = Column(Text, nullable=False)
    intent = Column(String(100))
    response = Column(Text)
    used_live_data = Column(String(5), default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TravelTimeLog(Base):
    __tablename__ = "travel_time_logs"

    id = Column(Integer, primary_key=True, index=True)
    dest_name = Column(String(255), nullable=False)   # normalized destination name
    dest_lat = Column(Float, nullable=False)
    dest_lng = Column(Float, nullable=False)
    day_of_week = Column(Integer, nullable=False)     # 0=Monday … 6=Sunday
    hour = Column(Integer, nullable=False)            # departure hour 0-23
    travel_time_mins = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
