from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    url = get_settings().database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    opts = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite:") else {"pool_pre_ping": True}
    return create_engine(url, **opts)


def session_factory():
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def db_session():
    with session_factory()() as db:
        yield db
