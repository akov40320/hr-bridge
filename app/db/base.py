"""Shared declarative base for SQLAlchemy models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):  # pylint: disable=too-few-public-methods
    """Base class for all SQLAlchemy models."""

