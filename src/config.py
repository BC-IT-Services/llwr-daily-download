"""Mounted-file configuration, matching the other microservices.

    /config/ipc_config.json   - shared RabbitMQ / Redis broker settings
    /config/llwr_config.json  - portal credentials, report parameters, Drive target
    /secrets/token.json       - Google token (own mount point, WRITABLE;
                                override with GOOGLE_CONFIG_DIR)

Environment variables remain a fallback so local runs keep working.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

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

    # Deliberately NOT under /config: that mount is read-only by convention in
    # our stacks, and the token has to be writable so refreshes persist. A
    # writable mount nested inside a read-only one also fails outright at
    # container start (Docker cannot create the mountpoint), so the writable
    # secret gets its own top-level path.
    GOOGLE_DIR_DEFAULT = "/secrets"

    @property
    def google_dir(self) -> Path:
        return Path(
            self._section("google", "dir", "GOOGLE_CONFIG_DIR", self.GOOGLE_DIR_DEFAULT)
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
    def redis_result_db(self) -> int:
        """Redis DB for Celery results.

        Must match what the *gateway* reads from, because the gateway is what
        polls these task results to decide a run finished. The gateway builds
        its backend from `redis.cache_db`, so that is the source of truth here
        - not `redis.celery_db`, which the gateway never reads and which
        ipc_config.json does not even define. Getting this wrong does not fail
        loudly: the task runs and stores its result somewhere the gateway never
        looks, so the job simply never leaves "running".

        Set `celery.result_backend_db` to override deliberately.
        """
        explicit = self.ipc_config.get("celery", {}).get("result_backend_db")
        if explicit is not None:
            return int(explicit)
        return int(self.ipc_config.get("redis", {}).get("cache_db", 0))

    @property
    def celery_broker_url(self) -> str:
        # Built exactly as the gateway builds it, password-encoding included.
        encoded_pass = quote_plus(self.rabbitmq_password)
        vhost_part = f"/{self.rabbitmq_vhost}" if self.rabbitmq_vhost else "/"
        return (
            f"amqp://{self.rabbitmq_user}:{encoded_pass}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}{vhost_part}"
        )

    @property
    def celery_result_backend(self) -> str:
        encoded_pass = quote_plus(self.redis_password)
        return (
            f"redis://:{encoded_pass}@{self.redis_host}:"
            f"{self.redis_port}/{self.redis_result_db}"
        )

    @property
    def celery_task_timeout(self) -> int:
        return self.ipc_config.get("celery", {}).get("llwr_task_timeout", 1800)


settings = Settings()
