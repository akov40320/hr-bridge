import logging, sys


def setup_logging(level: str = "INFO"):
    root = logging.getLogger()
    root.setLevel(level)
    h = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s | %(message)s')
    h.setFormatter(fmt)
    root.handlers = [h]
