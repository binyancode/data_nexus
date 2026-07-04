from pydantic import BaseModel
from typing import Optional


class BaseSchema(BaseModel):
    class Config:
        from_attributes = True
