import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


APP_NAME = os.getenv("APP_NAME", "mwobareullae")
API_BASE_PATH = os.getenv("API_BASE_PATH", "/api")
cors_origins = [
    origin.strip()
    for origin in os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app = FastAPI(title=f"{APP_NAME} API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "service": APP_NAME,
        "message": "hello from mwobareullae backend",
        "health": f"{API_BASE_PATH}/health",
    }


@app.get(f"{API_BASE_PATH}/health")
def health():
    return {
        "status": "ok",
        "service": APP_NAME,
    }
