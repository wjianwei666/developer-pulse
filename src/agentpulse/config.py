from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_path: Path = DATA_DIR / "agentpulse.db"

    openrouter_url: str = "https://openrouter.ai/api/v1/models"
    openrouter_poll_hours: int = 6

    github_repos: list[str] = [
        "microsoft/mastra",
        "langchain-ai/langgraph",
        "modelcontextprotocol/servers",
        "openai/openai-python",
        "anthropics/anthropic-sdk-python",
        "langchain-ai/langchain",
        "Vercel/ai",
        "crewAIInc/crewAI",
        "agno-agi/agno",
        "run-llama/llama_index",
        "deepset-ai/haystack",
        "microsoft/autogen",
        "google-deepmind/deepagents",
        "langfuse/langfuse",
        "weaviate/weaviate",
        "chroma-core/chroma",
        "qdrant/qdrant-client",
        "huggingface/transformers",
        "ollama/ollama",
        "natemoo-re/clack",
        "browser-use/browser-use",
        "ComposioHQ/composio",
        "letta-ai/letta",
        "OpenInterpreter/open-interpreter",
        "cogentai/cogent",
    ]
    github_poll_hours: int = 2

    mcp_registry_url: str = "https://registry.mcp.so/v0/servers"
    mcp_poll_hours: int = 24

    request_user_agent: str = "AgentPulse/0.1 (monitoring service; contact: ops@agentpulse.local)"
    request_timeout: int = 30
    request_pagination_interval: float = 0.3

    digest_time_utc: str = "07:00"

    blended_cache_ratio: float = 0.7
    blended_input_ratio: float = 0.2
    blended_output_ratio: float = 0.1

    price_noise_threshold_pct: float = 0.5

    score_alert_threshold: int = 70
    score_digest_threshold: int = 40

    site_host: str = "0.0.0.0"
    site_port: int = 7050

    slack_webhook_url: str = ""
    discord_webhook_url: str = ""

    github_client_id: str = ""
    github_client_secret: str = ""
    github_oauth_redirect_uri: str = "http://localhost:7050/auth/github/callback"
    session_secret: str = "change-me-in-production"

    default_adoption_weights: dict[str, int] = {
        "openai": 100,
        "anthropic": 95,
        "google": 90,
        "meta": 80,
        "microsoft": 85,
        "x-ai": 60,
        "mistral": 55,
        "cohere": 45,
        "deepseek": 50,
        "moonshot": 35,
    }


settings = Settings()