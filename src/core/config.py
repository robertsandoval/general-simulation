from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Postgres (used directly by /graph and /live) ---
    postgres_dsn: str = Field(
        default="postgresql://sim:sim@localhost:5432/sim",
        description="asyncpg-compatible DSN for the shared Postgres instance.",
    )

    # --- Llama Stack (all inference, embedding, and vector/RAG go here) ---
    llama_stack_base_url: str = Field(
        default="http://localhost:8321",
        description="Base URL of the running Llama Stack server.",
    )

    # --- Model identifiers (registered inside Llama Stack's run.yaml) ---
    generation_model_id: str = Field(
        default="meta-llama/Llama-3.1-8B-Instruct",
        description="Model id for text generation, as registered in Llama Stack.",
    )
    embedding_model_id: str = Field(
        default="all-MiniLM-L6-v2",
        description="Model id for embeddings, as registered in Llama Stack.",
    )
    embedding_dimension: int = Field(
        default=384,
        description="Vector dimension of the chosen embedding model.",
    )

    # --- Runtime mode ---
    use_fake_llama_stack: bool = Field(
        default=False,
        description=(
            "When True, the app uses FakeLlamaStackClient so the full stack "
            "runs without a GPU or a live Llama Stack server."
        ),
    )
