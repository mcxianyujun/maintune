import json
import time
import uuid
from pathlib import Path

from sqlalchemy import JSON, Float, Integer, String, Text, UniqueConstraint, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Config(Base):
    __tablename__ = "config"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    data: Mapped[dict] = mapped_column(JSON)
    encrypted_key: Mapped[str | None] = mapped_column(Text, nullable=True)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    started: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    ended: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    data: Mapped[dict] = mapped_column(JSON)


class Usage(Base):
    __tablename__ = "usage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    timestamp: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    run_id: Mapped[str] = mapped_column(String(36))
    data: Mapped[dict] = mapped_column(JSON)


class RuntimeSnapshot(Base):
    __tablename__ = "runtime_snapshots"
    __table_args__ = (UniqueConstraint("task_id", "agent_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_id: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)


class ConfigAudit(Base):
    __tablename__ = "config_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    timestamp: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    data: Mapped[dict] = mapped_column(JSON)


class Repository(Base):
    __tablename__ = "repositories"
    full_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    installation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data: Mapped[dict] = mapped_column(JSON)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    delivery_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    received: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    event: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80), default="")
    repository: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="accepted")
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    repository: Mapped[str] = mapped_column(String(255), index=True)
    number: Mapped[int] = mapped_column(Integer, index=True)
    event: Mapped[str] = mapped_column(String(80))
    delivery_id: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    updated: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(JSON)


class Timeline(Base):
    __tablename__ = "timeline"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    timestamp: Mapped[float] = mapped_column(Float, default=time.time)
    kind: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON)


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (UniqueConstraint("action_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    action_key: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    data: Mapped[dict] = mapped_column(JSON)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReviewFinding(Base):
    __tablename__ = "review_findings"
    __table_args__ = (UniqueConstraint("repository", "number", "fingerprint"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    repository: Mapped[str] = mapped_column(String(255), index=True)
    number: Mapped[int] = mapped_column(Integer, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    head_sha: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)


def migrate(engine) -> None:
    """Small explicit migration ledger; schema and JSON migrations are additive."""
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at FLOAT NOT NULL)"))
        current = connection.execute(text("SELECT COALESCE(MAX(version), 1) FROM schema_migrations")).scalar_one()
    if current < 2:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (2, :now)"), {"now": time.time()})
    if current < 3:
        with engine.begin() as connection:
            def decoded(value):
                return json.loads(value) if isinstance(value, str) else dict(value or {})

            for row in connection.execute(text("SELECT id, data FROM providers")).mappings():
                data = decoded(row["data"])
                models = data.get("models", [])
                if any(isinstance(item, str) for item in models):
                    data["models"] = [
                        {"id": item, "display_name": None, "enabled": True, "capabilities": {}, "defaults": {}}
                        if isinstance(item, str) else item
                        for item in models
                    ]
                    connection.execute(text("UPDATE providers SET data=:data WHERE id=:id"), {"id": row["id"], "data": json.dumps(data)})

            general = connection.execute(text("SELECT data FROM config WHERE id='general'")).scalar_one_or_none()
            if general is not None:
                data = decoded(general)
                old_steps, old_timeout = data.pop("max_steps", None), data.pop("timeout", None)
                if old_steps is not None and "steps" not in data:
                    data["steps"] = {"mode": "fixed", "fixed_steps": old_steps, "soft_limit": old_steps, "hard_limit": old_steps, "extension": 20, "loop_threshold": 3}
                if old_timeout is not None and "timeouts" not in data:
                    data["timeouts"] = {"model_request": old_timeout, "tool_call": old_timeout, "agent_task": old_timeout, "sandbox_ttl": 3600}
                data.setdefault("reasoning", {})
                data.setdefault("generation", {})
                connection.execute(text("UPDATE config SET data=:data WHERE id='general'"), {"data": json.dumps(data)})

            for row in connection.execute(text("SELECT id, data FROM agents")).mappings():
                data = decoded(row["data"])
                if "runtime" not in data:
                    data["runtime"] = {}
                    connection.execute(text("UPDATE agents SET data=:data WHERE id=:id"), {"id": row["id"], "data": json.dumps(data)})
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (3, :now)"), {"now": time.time()})
    if current < 4:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (4, :now)"), {"now": time.time()})


def database(url: str):
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 20} if url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    migrate(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
