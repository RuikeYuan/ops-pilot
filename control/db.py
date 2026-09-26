import os
import time
import uuid
from pathlib import Path

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid():
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = 'accounts'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_salt: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Client(Base):
    __tablename__ = 'clients'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(32), default='legacy', server_default='legacy', index=True)
    name: Mapped[str] = mapped_column(String(120))
    contact: Mapped[str] = mapped_column(String(160), default='')
    color: Mapped[str] = mapped_column(String(20), default='teal')


class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    client_id: Mapped[str] = mapped_column(ForeignKey('clients.id'))
    name: Mapped[str] = mapped_column(String(120))
    environment: Mapped[str] = mapped_column(String(30), default='Production')
    provider: Mapped[str] = mapped_column(String(40), default='Other')
    mode: Mapped[str] = mapped_column(String(20), default='http')
    url: Mapped[str] = mapped_column(String(2048), default='')
    interval: Mapped[int] = mapped_column(Integer, default=300)
    expected_status: Mapped[int] = mapped_column(Integer, default=200)
    token_hash: Mapped[str] = mapped_column(String(64), default='')
    created: Mapped[float] = mapped_column(Float, default=time.time)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    fault: Mapped[bool] = mapped_column(Boolean, default=False)


class Check(Base):
    __tablename__ = 'checks'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    latency: Mapped[float] = mapped_column(Float, default=0)
    detail: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default='manual')


class Incident(Base):
    __tablename__ = 'incidents'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default='open')
    severity: Mapped[str] = mapped_column(String(20), default='major')
    opened: Mapped[float] = mapped_column(Float, default=time.time)
    resolved: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default='')


class Event(Base):
    __tablename__ = 'audit_events'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(32), default='legacy', server_default='legacy', index=True)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    at: Mapped[float] = mapped_column(Float, default=time.time)
    kind: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text)


class Deployment(Base):
    __tablename__ = 'deployments'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    at: Mapped[float] = mapped_column(Float, default=time.time)
    version: Mapped[str] = mapped_column(String(120))
    commit: Mapped[str] = mapped_column(String(80), default='')
    status: Mapped[str] = mapped_column(String(30), default='pending')


class BusinessRun(Base):
    __tablename__ = 'business_runs'
    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    at: Mapped[float] = mapped_column(Float, default=time.time)
    observed_at: Mapped[float] = mapped_column(Float)
    workflow: Mapped[str] = mapped_column(String(60))
    steps_json: Mapped[str] = mapped_column(Text)


def database(url=None):
    Path('data').mkdir(exist_ok=True)
    url = url or os.getenv('DATABASE_URL', 'sqlite:///data/control.db')
    if url.startswith(('postgres://', 'postgresql://')):
        url = 'postgresql+psycopg://' + url.split('://', 1)[1]
    engine = create_engine(url, connect_args={'check_same_thread': False} if url.startswith('sqlite') else {}, pool_pre_ping=True)
    # Additive, repeatable migration: existing shared data remains operator-only.
    # Run one application replica while upgrading.
    with engine.begin() as connection:
        schema = inspect(connection)
        for table in ('clients', 'audit_events'):
            if schema.has_table(table) and 'workspace_id' not in {c['name'] for c in schema.get_columns(table)}:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN workspace_id VARCHAR(32) NOT NULL DEFAULT 'legacy'"))
                connection.execute(text(f"CREATE INDEX ix_{table}_workspace_id ON {table} (workspace_id)"))
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
