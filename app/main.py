from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.routes import knowledge, faqs, incidents, query, route, prediction, roads
from app.services.incident_sync import run_incident_sync_loop
from app.services.flow_sync import run_flow_sync_loop
import asyncio

Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background jobs on startup
    incident_task = asyncio.create_task(run_incident_sync_loop())
    flow_task = asyncio.create_task(run_flow_sync_loop())
    yield
    # Cancel on shutdown
    incident_task.cancel()
    flow_task.cancel()

app = FastAPI(
    title="Traffic Information Assistant API",
    description="Backend API for the traffic information assistant platform",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://traffic-ai-frontend-j9k8-1icnikbgn-minkhantko650s-projects.vercel.app",
    ],
    allow_origin_regex=r"https://traffic-ai-frontend.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(knowledge.router)
app.include_router(faqs.router)
app.include_router(incidents.router)
app.include_router(query.router)
app.include_router(route.router)
app.include_router(prediction.router)
app.include_router(roads.router)

@app.get("/")
def root():
    return {"message": "Traffic Information Assistant API is running"}

@app.get("/health")
def health():
    return {"status": "ok"}
