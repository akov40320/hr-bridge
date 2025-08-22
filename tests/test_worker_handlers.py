import asyncio
import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import worker_rmq


@pytest.mark.parametrize(
    "key,func",
    [
        (("hh", "send_message"), worker_rmq.handle_hh_send_message),
        (("avito", "send_message"), worker_rmq.handle_avito_send_message),
        (("mirror", "amo_to_tg"), worker_rmq.handle_mirror_amo_to_tg),
    ],
)
def test_handler_mapping(key, func):
    assert worker_rmq.HANDLERS[key] is func
