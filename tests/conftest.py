import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.services.seed_service import seed_database
from app.main import app

TEST_DB_FILE = "./test_niftytrade.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"

test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except Exception:
            pass

    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    seed_database(db, force_reset=True)
    from app.models.user import User
    from app.core.security import hash_password
    u1 = User(
        username="demo1",
        email="demo1@niftytrade.local",
        hashed_password=hash_password("demo123"),
        full_name="Test User 1",
        client_id="NT0001",
        masked_pan="ABCDE1234F",
        masked_demat="1208160012345678",
        mobile="9876543210",
        available_funds=185420.50,
        used_margin=15600.00
    )
    u2 = User(
        username="demo2",
        email="demo2@niftytrade.local",
        hashed_password=hash_password("demo123"),
        full_name="Test User 2",
        client_id="NT0002",
        masked_pan="FGHIJ5678K",
        masked_demat="1208160087654321",
        mobile="9876543211",
        available_funds=240500.00,
        used_margin=0.00
    )
    db.add(u1)
    db.add(u2)
    db.commit()

    from app.models.trading import Holding
    from app.models.instrument import Instrument
    inst = db.query(Instrument).first()
    if inst:
        db.add(Holding(user_id=u1.id, instrument_id=inst.id, quantity=10, average_price=inst.current_price))
        db.commit()

    db.close()

    yield

    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except Exception:
            pass

@pytest.fixture
def test_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
