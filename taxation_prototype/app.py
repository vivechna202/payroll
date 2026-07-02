"""
Backward-compatible entry point for TaxPro HRMS (FastAPI).

Run:
    python app.py
"""
from app.main import app
from app.base.utils.config import DEBUG

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=5050, reload=DEBUG)
