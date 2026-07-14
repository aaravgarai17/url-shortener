from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import base62, cache
from app.config import settings
from app.database import Base, engine, get_db
from app.models import URL
from app.rate_limiter import is_allowed
from app.schemas import ShortenRequest, ShortenResponse, StatsResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on boot. In production this would be an Alembic migration.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="URL Shortener",
    description="A TinyURL-style service demonstrating base62 encoding, "
    "cache-aside reads, and distributed rate limiting.",
    version="1.0.0",
    lifespan=lifespan,
)


def rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    if not is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/api/shorten",
    response_model=ShortenResponse,
    dependencies=[Depends(rate_limit)],
    status_code=201,
)
def shorten(payload: ShortenRequest, db: Session = Depends(get_db)):
    """Create a short code for a long URL.

    Insert first to obtain the auto-increment id, then derive the short_code
    from that id via base62. This avoids any collision-detection loop.
    """
    url = URL(short_code="", long_url=str(payload.long_url))
    db.add(url)
    db.flush()  # assigns url.id without committing

    url.short_code = base62.encode(url.id)
    db.commit()
    db.refresh(url)

    cache.set_long_url(url.short_code, url.long_url)
    return ShortenResponse(
        short_code=url.short_code,
        short_url=f"{settings.base_url}/{url.short_code}",
        long_url=url.long_url,
    )


@app.get("/api/stats/{short_code}", response_model=StatsResponse)
def stats(short_code: str, db: Session = Depends(get_db)):
    url = db.query(URL).filter(URL.short_code == short_code).first()
    if url is None:
        raise HTTPException(status_code=404, detail="Short code not found")
    return StatsResponse(
        short_code=url.short_code,
        long_url=url.long_url,
        click_count=url.click_count,
        created_at=url.created_at,
    )


@app.get("/{short_code}")
def redirect(short_code: str, db: Session = Depends(get_db)):
    """Resolve a short code and 301-redirect to the long URL.

    Cache-aside: try Redis first; on miss, read Postgres and backfill the cache.
    Click counting is best-effort and does not block the redirect.
    """
    long_url = cache.get_long_url(short_code)

    if long_url is None:
        url = db.query(URL).filter(URL.short_code == short_code).first()
        if url is None:
            raise HTTPException(status_code=404, detail="Short code not found")
        long_url = url.long_url
        cache.set_long_url(short_code, long_url)

    # Increment analytics without a full ORM load.
    db.query(URL).filter(URL.short_code == short_code).update(
        {URL.click_count: URL.click_count + 1}
    )
    db.commit()

    return RedirectResponse(url=long_url, status_code=301)
