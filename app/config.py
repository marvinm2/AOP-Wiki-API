"""Runtime settings, read from environment variables (or a local .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

QUERIES_DIR = Path(__file__).resolve().parent.parent / "queries"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # In the swarm this is the stack-qualified Virtuoso service on the `core` overlay:
    # http://aopwiki-snorql_virtuoso:8890/sparql
    sparql_endpoint: str = "https://aopwiki.rdf.bigcat-bioinformatics.org/sparql"
    data_graph: str = "http://aopwiki.org/"
    dataset_iri: str = "https://aopwiki.rdf.bigcat-bioinformatics.org/AOPWikiRDF"
    public_base_url: str = "https://aopwiki.api.bigcat-bioinformatics.org"

    sparql_connect_timeout_s: float = 2.0
    sparql_timeout_s: float = 10.0
    federated_timeout_s: float = 30.0
    # Virtuoso's ResultSetMaxRows: results of exactly this size are silently truncated.
    virtuoso_row_cap: int = 10_000

    version_poll_interval_s: float = 300.0
    cache_max_entries: int = 4096

    default_limit: int = 100
    max_limit: int = 1000

    queries_dir: Path = QUERIES_DIR


@lru_cache
def get_settings() -> Settings:
    return Settings()
