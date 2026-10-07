import uvicorn
from fastapi import FastAPI

from app.api import router as layout_router

app = FastAPI(title="Dungeon Layout Generator", version="0.2.0")
app.include_router(layout_router, prefix="/api")


@app.get("/")
def read_root():
    return {"service": "dungeon-layout-generator", "docs": "/docs"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=0)
