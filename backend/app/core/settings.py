from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_COMPANY_TARGETS_FILE = (
    Path(__file__).resolve().parents[1] / "scrapers" / "company_targets.json"
)


class Settings(BaseSettings):
    aws_region: str | None = Field(default=None, alias="AWS_REGION")
    dynamodb_table_name: str | None = Field(
        default=None, alias="DYNAMODB_TABLE_NAME"
    )
    dynamodb_endpoint_url: str | None = Field(
        default=None, alias="DYNAMODB_ENDPOINT_URL"
    )
    scraper_enabled_sources: str = Field(
        default=(
            "jobs.ch,jobup.ch,swissdevjobs.ch,"
            "company:scandit,company:on-running,company:rivr,company:swissborg"
        ),
        alias="SCRAPER_ENABLED_SOURCES",
    )
    scraper_company_targets_file: Path = Field(
        default=DEFAULT_COMPANY_TARGETS_FILE,
        alias="SCRAPER_COMPANY_TARGETS_FILE",
    )
    scraper_user_agent: str = Field(
        default=(
            "JobDataBot/0.1 "
            "(private job-market research; contact: set SCRAPER_CONTACT)"
        ),
        alias="SCRAPER_USER_AGENT",
    )
    scraper_contact: str | None = Field(default=None, alias="SCRAPER_CONTACT")
    scraper_connect_timeout_seconds: float = Field(
        default=5, ge=0.1, alias="SCRAPER_CONNECT_TIMEOUT_SECONDS"
    )
    scraper_read_timeout_seconds: float = Field(
        default=20, ge=0.1, alias="SCRAPER_READ_TIMEOUT_SECONDS"
    )
    scraper_max_retries: int = Field(
        default=3, ge=0, le=10, alias="SCRAPER_MAX_RETRIES"
    )
    scraper_retry_backoff_seconds: float = Field(
        default=1, ge=0, alias="SCRAPER_RETRY_BACKOFF_SECONDS"
    )
    scraper_requests_per_second: float = Field(
        default=1, gt=0, alias="SCRAPER_REQUESTS_PER_SECOND"
    )
    scraper_max_pages: int = Field(
        default=2_000, ge=1, alias="SCRAPER_MAX_PAGES"
    )
    scraper_source_max_workers: int = Field(
        default=3, ge=1, le=3, alias="SCRAPER_SOURCE_MAX_WORKERS"
    )
    api_cors_origins: str = Field(
        default="http://localhost:3000", alias="API_CORS_ORIGINS"
    )

    model_config = SettingsConfigDict(env_file=PROJECT_ENV_FILE, extra="ignore")

    @property
    def effective_user_agent(self) -> str:
        if not self.scraper_contact:
            return self.scraper_user_agent
        return f"{self.scraper_user_agent} ({self.scraper_contact})"

    @property
    def enabled_source_names(self) -> tuple[str, ...]:
        return tuple(
            name.strip().casefold()
            for name in self.scraper_enabled_sources.split(",")
            if name.strip()
        )

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.api_cors_origins.split(",")
            if origin.strip()
        ]

    def require_dynamodb(self) -> tuple[str, str]:
        missing = [
            name
            for name, value in (
                ("AWS_REGION", self.aws_region),
                ("DYNAMODB_TABLE_NAME", self.dynamodb_table_name),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "Missing required DynamoDB configuration: "
                + ", ".join(missing)
            )
        return self.aws_region, self.dynamodb_table_name


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_local_environment() -> None:
    """Expose root .env values to libraries that use normal environment lookup."""
    # override=False keeps exported variables, IAM/container configuration, and
    # other production credential sources ahead of local development values.
    load_dotenv(PROJECT_ENV_FILE, override=False)
