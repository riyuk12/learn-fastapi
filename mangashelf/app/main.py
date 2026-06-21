from fastapi import FastAPI
import uvicorn

app= FastAPI(title="MangaShelf", description="A simple API for managing manga", version="0.1.0")

@app.get("/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)