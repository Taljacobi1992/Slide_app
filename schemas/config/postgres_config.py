"""
from typing import Optional
from pydantic import BaseModel


class postgreConfig(BaseModel):
    base_url: str
    search_route: str
    top_k_value: str
"""