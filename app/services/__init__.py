"""Initialization for the services package.

This package exposes selected helper functions for use throughout the
application, such as :func:`tg_send_with_retry`.
"""

from .telegram import tg_send_with_retry

__all__ = ["tg_send_with_retry"]
