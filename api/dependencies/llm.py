from api.llm.base import LLMClient
from api.llm.gemini_client import GeminiClient

_llm_client: LLMClient = GeminiClient()


def get_llm_client() -> LLMClient:
    return _llm_client


def set_llm_client(client: LLMClient) -> None:
    global _llm_client
    _llm_client = client
