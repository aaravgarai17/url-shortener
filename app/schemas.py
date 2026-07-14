from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class ShortenRequest(BaseModel):
    long_url: HttpUrl = Field(..., description="The URL to shorten")


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str


class StatsResponse(BaseModel):
    short_code: str
    long_url: str
    click_count: int
    created_at: datetime
