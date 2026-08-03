import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.services.solution_engine import SolutionEngine

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="BoonTrack Core API",
    description="Backend engine for BoonTrack Assistant",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

solution_engine = SolutionEngine()


@app.get("/")
async def root():
    return {"status": "online", "message": "BoonTrack Core Engine is Running"}


@app.get("/api/v1/search")
async def search_endpoint(q: str = ""):
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter 'q' cannot be empty.")
    result = await solution_engine.find_solution(user_message=q)
    return result
