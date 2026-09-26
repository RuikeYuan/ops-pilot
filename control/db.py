import os
import time
import uuid
from pathlib import Path

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid():
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Client(Base):
    __tablename__ = 'clients'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
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
    engine = create_engine(url, connect_args={'check_same_thread': False} if url.startswith('sqlite') else {}, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
