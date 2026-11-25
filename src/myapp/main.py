from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def home():
    return "<h1>Hello from my app</h1>"

def run():
    uvicorn.run(app, host="0.0.0.0", port=8000)
