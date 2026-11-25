from fastapi.testclient import TestClient
from myapp.main import app

client = TestClient(app)

def test_home():
    response = client.get("/")
    assert response.status_code == 200
    assert "Hello" in response.text
