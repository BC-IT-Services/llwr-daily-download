"""Mounted-file configuration, matching the other microservices.

    /config/ipc_config.json   - shared RabbitMQ / Redis broker settings
    /config/llwr_config.json  - portal credentials, report parameters, Drive target
    /config/google/           - credentials.json + token.json (mounted writable)

Environment variables remain a fallback so local runs keep working.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/config"))


class ConfigurationError(Exception):
    pass


class ConfigManager:
    def __init__(self, config_dir: Path | str = CONFIG_DIR):
        self.config_dir = Path(config_dir)
        self._configs: dict[str, dict[str, Any]] = {}

    def load_config(self, config_name: str) -> dict[str, Any]:
        if config_name in self._configs:
            return self._configs[config_name]

        config_path = self.config_dir / f"{config_name}.json"
        if not config_path.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")

        try:
            with open(config_path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in {config_name}: {e}") from e
        except Exception as e:
            raise ConfigurationError(f"Error loading {config_name}: {e}") from e

        self._configs[config_name] = data
        logger.info(f"Loaded configuration: {config_name}")
        return data

    def load_optional(self, config_name: str) -> dict[str, Any]:
        try:
            return self.load_config(config_name)
        except ConfigurationError as e:
            logger.warning(f"{e} - falling back to environment variables")
            return {}


class Settings:
    def __init__(self, config_manager: ConfigManager | None = None):
        self.config_manager = config_manager or ConfigManager()
        self.ipc_config = self.config_manager.load_optional("ipc_config")
        self.llwr_config = self.config_manager.load_optional("llwr_config")

    def _section(self, section: str, key: str, env_var: str, default: Any = None) -> Any:
        value = (self.llwr_config.get(section) or {}).get(key)
        if value in (None, ""):
            value = os.getenv(env_var)
        return default if value in (None, "") else value

    # --- Post-16 portal ---

    @property
    def portal_username(self) -> str:
        return self._section("portal", "username", "PORTAL_USER", "")

    @property
    def portal_password(self) -> str:
        return self._section("portal", "password", "PORTAL_PASS", "")

    @property
    def portal_login_url(self) -> str:
        return self._section(
            "portal", "login_url", "PORTAL_LOGIN_URL",
            "https://post16-portal-service.gov.wales/login",
        )

    @property
    def report_url(self) -> str:
        return self._section(
            "report", "url", "LLWR_REPORT_URL",
            "https://post16-portal-service.gov.wales/Inform/Reports/RenderInNewWindow.aspx?r=48",
        )

    @property
    def report_provider(self) -> str:
        return self._section(
            "report", "provider", "LLWR_PROVIDER", "Bridgend College (F0009004)"
        )

    @property
    def report_year(self) -> str:
        """Academic year shown in the report's Year dropdown, e.g. '2025'."""
        return str(self._section("report", "year", "LLWR_YEAR", ""))

    @property
    def report_third_parameter(self) -> str:
        return self._section("report", "third_parameter", "LLWR_THIRD_PARAM", "All")

    @property
    def page_timeout_seconds(self) -> int:
        return int(self._section("report", "page_timeout_seconds", "LLWR_TIMEOUT", 30))

    @property
    def download_timeout_seconds(self) -> int:
        return int(
            self._section("report", "download_timeout_seconds", "LLWR_DOWNLOAD_TIMEOUT", 60)
        )

    # --- Output / Drive ---

    @property
    def download_dir(self) -> str:
        return self._section("output", "download_dir", "LLWR_DOWNLOAD_DIR", "/data/csvs")

    @property
    def drive_folder_id(self) -> str:
        return self._section(
            "output", "drive_folder_id", "LLWR_DRIVE_FOLDER_ID",
            "1f5GmoNA4CqJ8csagO3-y5l6835TRPkr2",
        )

    @property
    def upload_to_drive(self) -> bool:
        value = (self.llwr_config.get("output") or {}).get("upload_to_drive")
        if value is None:
            value = os.getenv("LLWR_UPLOAD_TO_DRIVE", "true")
        return str(value).lower() not in ("false", "0", "no")

    @property
    def keep_local_copy(self) -> bool:
        value = (self.llwr_config.get("output") or {}).get("keep_local_copy")
        if value is None:
            value = os.getenv("LLWR_KEEP_LOCAL", "true")
        return str(value).lower() not in ("false", "0", "no")

    # --- Google auth (mounted, non-interactive) ---

    @property
    def google_dir(self) -> Path:
        return Path(
            self._section("google", "dir", "GOOGLE_CONFIG_DIR", str(CONFIG_DIR / "google"))
        )

    @property
    def google_credentials_path(self) -> Path:
        return self.google_dir / "credentials.json"

    @property
    def google_token_path(self) -> Path:
        return self.google_dir / "token.json"

    # --- Chrome ---

    @property
    def chrome_binary(self) -> str:
        return self._section("chrome", "binary", "CHROME_BINARY", "/usr/bin/chromium")

    # --- Celery / broker ---

    @property
    def rabbitmq_user(self) -> str:
        return self.ipc_config.get("rabbitmq", {}).get("user", "guest")

    @property
    def rabbitmq_password(self) -> str:
        return self.ipc_config.get("rabbitmq", {}).get("password", "guest")

    @property
    def rabbitmq_host(self) -> str:
        return self.ipc_config.get("rabbitmq", {}).get("host", "rabbitmq")

    @property
    def rabbitmq_port(self) -> int:
        return self.ipc_config.get("rabbitmq", {}).get("port", 5672)

    @property
    def rabbitmq_vhost(self) -> str | None:
        return self.ipc_config.get("rabbitmq", {}).get("vhost")

    @property
    def redis_host(self) -> str:
        return self.ipc_config.get("redis", {}).get("host", "redis")

    @property
    def redis_port(self) -> int:
        return self.ipc_config.get("redis", {}).get("port", 6379)

    @property
    def redis_password(self) -> str:
        return self.ipc_config.get("redis", {}).get("password", "")

    @property
    def redis_celery_db(self) -> int:
        return self.ipc_config.get("redis", {}).get("celery_db", 1)

    @property
    def celery_broker_url(self) -> str:
        vhost = f"/{self.rabbitmq_vhost}" if self.rabbitmq_vhost else "//"
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}{vhost}"
        )

    @property
    def celery_result_backend(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_celery_db}"

    @property
    def celery_task_timeout(self) -> int:
        return self.ipc_config.get("celery", {}).get("llwr_task_timeout", 1800)


settings = Settings()
