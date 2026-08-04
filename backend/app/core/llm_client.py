from app.config import settings


class LLMClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.gemini_api_key

    async def get_recommendations(self, context: dict) -> str:
        raise NotImplementedError
