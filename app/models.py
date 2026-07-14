from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String

from app.database import Base


class URL(Base):
    """A shortened URL record.

    The primary key `id` is an auto-incrementing integer. The short code is
    derived from this id via base62 encoding, which guarantees uniqueness
    without collision checks and keeps codes short and monotonic.
    """

    __tablename__ = "urls"

    # BIGINT on Postgres; INTEGER on SQLite so tests get autoincrementing rowids.
    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    short_code = Column(String(16), unique=True, index=True, nullable=False)
    long_url = Column(String(2048), nullable=False)
    click_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
