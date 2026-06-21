from fastapi import FastAPI
import uvicorn
from app.api.v1.router import router as api_router

app= FastAPI(title="MangaShelf", description="A simple API for managing manga", version="0.1.0")

@app.get("/health")
def health_check():
    return {"status": "ok"}

app.include_router(api_router, prefix="/api/v1")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)