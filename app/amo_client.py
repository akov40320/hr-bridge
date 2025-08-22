class ReauthRequired(Exception):
    pass


class AmoClient:
    @classmethod
    async def create(cls, *_args, **_kwargs):
        return cls()

    async def create_leads(self, *_args, **_kwargs):
        pass

    async def add_note(self, *_args, **_kwargs):
        pass

    async def add_tags(self, *_args, **_kwargs):
        pass
