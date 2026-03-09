import asyncio
import json
import logging
import os

from pydantic import ValidationError

from api.llm.base import (
    LLMClient,
    LLMInvalidResponseError,
    LLMSchemaValidationError,
    LLMTimeoutError,
)
from api.llm.prompts import FEW_SHOT_EXAMPLES, SYSTEM_PROMPT
from api.llm.types import CategoryContext, EnrichmentResult, ProductContext

logger = logging.getLogger(__name__)


class GeminiClient(LLMClient):
    MAX_RETRIES = 3
    BACKOFF_SECONDS = [1, 2, 4]
    TIMEOUT_SECONDS = 30

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.model_name = model_name
        self._model = None
        self._few_shot_contents: list = []

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        if project:
            self._init_vertex(project)

    def _init_vertex(self, project: str) -> None:
        import vertexai
        from vertexai.generative_models import Content, Part

        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        vertexai.init(project=project, location=location)

        from vertexai.generative_models import GenerativeModel

        self._model = GenerativeModel(self.model_name)

        # Build few-shot contents as alternating user/model turns
        for example in FEW_SHOT_EXAMPLES:
            self._few_shot_contents.append(
                Content(role="user", parts=[Part.from_text(json.dumps(example["input"]))])
            )
            self._few_shot_contents.append(
                Content(role="model", parts=[Part.from_text(json.dumps(example["output"]))])
            )

        logger.info(
            "Vertex AI initialized: project=%s location=%s model=%s",
            project,
            location,
            self.model_name,
        )

    async def enrich(
        self,
        product: ProductContext,
        category_context: CategoryContext,
    ) -> EnrichmentResult:
        user_message = json.dumps(
            {
                "category_context": category_context.category,
                "product": product.model_dump(),
            }
        )

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                raw = await self._call_model(user_message)
                return self._parse_response(raw)
            except LLMTimeoutError as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.BACKOFF_SECONDS[attempt])
            except (LLMInvalidResponseError, LLMSchemaValidationError):
                raise

        raise last_error  # type: ignore[misc]

    async def _call_model(self, user_message: str) -> str:
        """Call the Gemini API via Vertex AI SDK."""
        if self._model is None:
            raise NotImplementedError(
                "GeminiClient._call_model requires GOOGLE_CLOUD_PROJECT to be set"
            )

        from vertexai.generative_models import Content, Part

        contents = [
            Content(role="user", parts=[Part.from_text(SYSTEM_PROMPT)]),
            *self._few_shot_contents,
            Content(role="user", parts=[Part.from_text(user_message)]),
        ]

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._model.generate_content, contents),
                timeout=self.TIMEOUT_SECONDS,
            )
            return response.text
        except asyncio.TimeoutError:
            raise LLMTimeoutError(f"Gemini call timed out after {self.TIMEOUT_SECONDS}s")
        except LLMTimeoutError:
            raise
        except Exception as e:
            if "timeout" in str(e).lower() or "deadline" in str(e).lower():
                raise LLMTimeoutError(str(e))
            raise LLMInvalidResponseError(f"Gemini API error: {e}")

    def _parse_response(self, raw: str) -> EnrichmentResult:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("LLM returned non-JSON: %s", raw[:500])
            raise LLMInvalidResponseError(f"Non-JSON response: {raw[:200]}")

        try:
            return EnrichmentResult.model_validate(data)
        except ValidationError as e:
            logger.error("LLM schema validation failed: %s | raw: %s", e, raw[:500])
            raise LLMSchemaValidationError(str(e))
