class SessionRepository:
    async def get_or_create(self, user_id: str, channel: str):
        class DummySession:
            def __init__(self):
                self.user_id = user_id
                self.channel = channel
                self.state = "START"
                self.goal = None
                self.context_json = {}
        return DummySession()

    async def save(self, session):
        pass
