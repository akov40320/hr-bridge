import logging


def setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level, logging.INFO))
