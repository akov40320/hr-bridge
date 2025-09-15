import asyncio
from app.store_chat import get_by_lead

async def main():
    lead_id = 20892297
    links = await get_by_lead(lead_id)
    for ln in links:
        print({'user_id': ln.user_id, 'bot_kind': ln.bot_kind, 'conversation_id': ln.conversation_id, 'lead_id': ln.lead_id})

asyncio.run(main())
