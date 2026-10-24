import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, db_session
from app.main import app


@pytest.fixture
def database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(database):
    def override():
        with database() as db:
            yield db
    app.dependency_overrides[db_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def two_users(client):
    users = []
    for email in ("one@example.com", "two@example.com"):
        result = client.post("/auth/register", json={"email":email,"password":"Test-password-12345", "organization_name":email})
        assert result.status_code == 201, result.text
        users.append(result.json())
    return users
