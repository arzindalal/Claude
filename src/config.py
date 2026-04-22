"""Central configuration. Loaded from .env."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    validation_model: str = Field(default="claude-opus-4-7", alias="VALIDATION_MODEL")
    screening_model: str = Field(default="claude-haiku-4-5", alias="SCREENING_MODEL")
    kb_dir: Path = Field(default=Path("./kb_data"), alias="KB_DIR")
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="EMBEDDING_MODEL",
    )

    @property
    def sqlite_path(self) -> Path:
        return self.kb_dir / "kb.sqlite"

    @property
    def chroma_path(self) -> Path:
        return self.kb_dir / "chroma"


settings = Settings()
