from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str
    SYNC_DATABASE_URL: str
    APP_ENV: str = "development"
    SECRET_KEY: str = "changeme"
    LOG_LEVEL: str = "INFO"          # DEBUG | INFO | WARNING | ERROR
    LOG_JSON: bool = True            # False = human-readable (dev), True = JSON (prod)

    # Keycloak — tokens are RS256-signed by https://sso.sudosys.org/realms/sudosys.
    # JWKS is fetched from the well-known endpoint at startup and cached in-process.
    KEYCLOAK_URL: str = "https://sso.sudosys.org"
    KEYCLOAK_REALM: str = "sudosys"

    # Internal service token — used by cron endpoints and Kafka consumer calls.
    # Pass as: Authorization: Bearer <INTERNAL_SERVICE_TOKEN>
    INTERNAL_SERVICE_TOKEN: str = "internal-dev-token-change-in-prod"


settings = Settings()
