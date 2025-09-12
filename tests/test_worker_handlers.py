import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app.services import worker_rmq
from app.services.worker import hh as worker_hh
from app.services.worker import avito as worker_avito
from app.services.worker import mirror as worker_mirror
from app.services.worker import amo as worker_amo


@pytest.mark.parametrize(
    "key,func",
    [
        (("hh", "send_message"), worker_hh.handle_hh_send_message),
        (("avito", "send_message"), worker_avito.handle_avito_send_message),
        (("mirror", "amo_to_tg"), worker_mirror.handle_mirror_amo_to_tg),
        (("amo", "amo_update_status"), worker_amo.handle_amo_update_status),
    ],
)
def test_handler_mapping(key, func):
    assert worker_rmq.HANDLERS[key] is func
