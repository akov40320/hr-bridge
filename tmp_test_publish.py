import asyncio
from datetime import datetime, timedelta
from app.api.api_amochats import publish_links

class DummyQueue:
    async def publish_task(self, payload):
        print('pub', payload['bot_kind'], payload['user_id'], payload['msg_key'][:20])

class Link:
    def __init__(self, bot_kind, user_id, updated_at):
        self.bot_kind = bot_kind
        self.user_id = user_id
        self.updated_at = updated_at

async def main():
    links = [
        Link('master', 1, datetime.utcnow() - timedelta(seconds=10)),
        Link('master', 2, datetime.utcnow()),
        Link('operator', 3, datetime.utcnow() - timedelta(seconds=5)),
        Link('operator', 4, datetime.utcnow() - timedelta(seconds=50)),
    ]
    await publish_links(DummyQueue(), links, 'conv', 'm1', 'hi')

asyncio.run(main())
