from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Jackett
    jackett_url: str = "http://localhost:9117"
    jackett_api_key: str = ""

    # TMDB
    tmdb_api_key: str = ""

    # WebDAV (Keenetic router storage)
    webdav_url: str = "https://segaa.keenetic.link/webdav/"
    webdav_user: str = ""
    webdav_pass: str = ""

    # Transmission
    transmission_host: str = "localhost"
    transmission_port: int = 9091
    transmission_path: str = "/transmission/rpc"
    transmission_user: str | None = None
    transmission_pass: str | None = None
    transmission_ssl: bool = False

    # OpenMemory (default localhost for local dev; overridden via OPENMEMORY_URL env var in production)
    openmemory_url: str = "http://localhost:8080"


settings = Settings()
