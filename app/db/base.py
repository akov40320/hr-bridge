"""Общий декларативный базовый класс для моделей SQLAlchemy."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):  # pylint: disable=too-few-public-methods
    """Базовый класс для всех моделей SQLAlchemy."""
