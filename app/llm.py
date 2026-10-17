"""Chat model factory. The answer chain only sees a LangChain BaseChatModel.

To add a provider, write a builder that returns a BaseChatModel and register it in
PROVIDERS. Planned (not implemented yet):

- "ollama": a local model on the home tower, via langchain-ollama (ChatOllama).
- "openai_compatible": the Localia inference API, via langchain-openai (ChatOpenAI with
  base_url pointing at Localia).
"""

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel

from app.config import Settings

PLANNED_PROVIDERS = ("ollama", "openai_compatible")


class UnknownProviderError(ValueError):
    pass


def _build_anthropic(settings: Settings) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    kwargs = {}
    if settings.llm_temperature is not None:
        kwargs["temperature"] = settings.llm_temperature
    return ChatAnthropic(
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        # Short grounded answers do not need reasoning tokens, which would also count
        # against max_tokens and the budget.
        thinking={"type": "disabled"},
        api_key=settings.anthropic_api_key,
        max_retries=2,
        default_request_timeout=30,
        **kwargs,
    )


PROVIDERS: dict[str, Callable[[Settings], BaseChatModel]] = {
    "anthropic": _build_anthropic,
}


def get_chat_model(settings: Settings) -> BaseChatModel:
    provider = settings.llm_provider.strip().lower()
    builder = PROVIDERS.get(provider)
    if builder is None:
        supported = ", ".join(sorted(PROVIDERS))
        planned = ", ".join(PLANNED_PROVIDERS)
        raise UnknownProviderError(
            f"Unknown LLM_PROVIDER '{settings.llm_provider}'. "
            f"Supported: {supported}. Planned, not implemented yet: {planned}."
        )
    return builder(settings)
