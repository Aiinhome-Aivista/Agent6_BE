import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

# We can optionally import our connection just to trigger the "Database connected" print
import database.connection 

# 1. Initialize FastAPI App
app = FastAPI(
    title=os.getenv("APP_NAME", "IUA API"),
    description="Enterprise AI-powered Insurance Underwriting System",
    version="1.0.0",
    docs_url="/docs",  # Swagger UI URL
    redoc_url="/redoc" # ReDoc URL
)

# Mount the static_graphs folder to serve interactive graph HTMLs via localhost HTTP URL
from fastapi.staticfiles import StaticFiles
static_dir = os.path.join(os.path.dirname(__file__), "static_graphs")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static_graphs", StaticFiles(directory=static_dir), name="static_graphs")

# Mount the uploads folder to serve uploaded documents
uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

# 2. Add Middleware (CORS)
# This allows the frontend to talk to the backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from controllers import auth, roles, cases, rulebooks, mail_config, claim_tracker
from scheduler.kb_scheduler import start_kb_scheduler, stop_kb_scheduler
from scheduler.escalation_scheduler import start_escalation_scheduler, stop_escalation_scheduler

# 3. Root Endpoint
@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint that provides basic information about the API.
    """
    return {
        "project": os.getenv("APP_NAME", "IUA API"),
        "description": "AI-powered Insurance Underwriting System Backend",
        "documentation": "/docs"
    }

# Register routers
app.include_router(auth.router)
app.include_router(roles.router)
app.include_router(cases.router)
app.include_router(rulebooks.router)
app.include_router(mail_config.router)
app.include_router(claim_tracker.router)

# Start background schedulers
@app.on_event("startup")
async def startup_event():
    start_kb_scheduler(interval_hours=6)          # Knowledge Base graph refresh
    start_escalation_scheduler(interval_minutes=1) # Underwriting SLA escalation check

@app.on_event("shutdown")
async def shutdown_event():
    stop_kb_scheduler()
    stop_escalation_scheduler()

# This block is for running the app directly using 'python main.py'
if __name__ == "__main__":
    import uvicorn
    debug_mode = os.getenv("DEBUG", "True").lower() == "true"
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=debug_mode
    )

