from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from typing import List

class CheckTransaction(BaseModel):
    check_number: str
    date: Optional[datetime] = None
    amount: Optional[float] = None
    payee: Optional[str] = None
    confidence: Optional[float] = None
    flagged_for_review: bool = False

class ProcessingResult(BaseModel):
    file_id: str
    checks: List[CheckTransaction]