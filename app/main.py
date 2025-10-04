from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from uuid import uuid4
import logging
import pandas as pd
from io import StringIO
from .models import CheckTransaction
from .parsers.statement_parser import parse_statement
import os 

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Check Payee Automation", version="0.1.0")

# Enable CORS for reviewer UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CheckResponse(BaseModel):
    check_number: str
    date: Optional[str] = None
    amount: Optional[float] = None

class SeedResponse(BaseModel):
    statement_id: str
    checks: List[CheckResponse]

@app.post("/checks/seed", response_model=SeedResponse)
async def seed_checks(file: UploadFile = File(...)):
    """
    Upload a single CSV bank statement with multiple sections (separated by blank rows),
    parse all sections to extract unique check numbers, optional dates, and amounts, and
    save a processed CSV with columns (Check Number, Date, Amount).
    The uploaded CSV is not saved to disk.
    """
    if not file.filename.endswith('.csv'):
        logger.error(f"Invalid file format: {file.filename}")
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    
    # Read file content without saving
    content = await file.read()
    if not content:
        logger.error(f"Empty file uploaded: {file.filename}")
        raise HTTPException(status_code=400, detail="Uploaded CSV file is empty")
    
    # Validate CSV content
    try:
        content_str = content.decode('utf-8')
        df = pd.read_csv(StringIO(content_str), dtype=str, keep_default_na=False, header=None)
        if df.empty:
            logger.error(f"CSV content is empty or invalid")
            raise HTTPException(status_code=400, detail="CSV file contains no data")
    except Exception as e:
        logger.error(f"Failed to read CSV: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid CSV format: {str(e)}")
    
    # Parse statement
    try:
        # Write temporary file for parsing (will be overwritten by _parsed.csv)
        statement_id = str(uuid4())
        temp_path = f"temp_{statement_id}.csv"
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(content_str)
        
        checks = parse_statement(temp_path)
        # Remove temporary file
        os.remove(temp_path)
        
        response_checks = [
            {
                "check_number": c.check_number,
                "date": c.date.strftime("%Y-%m-%d") if c.date else None,
                "amount": c.amount if c.amount is not None else None
            } for c in checks
        ]
        logger.info(f"Parsed {len(checks)} unique checks for statement_id: {statement_id}")
        return SeedResponse(statement_id=statement_id, checks=response_checks)
    except ValueError as e:
        logger.error(f"Parsing failed: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Parsing failed: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error parsing: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

@app.get("/health")
async def health_check():
    logger.info("Health check requested")
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)