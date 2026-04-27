"""Environment management for production/testnet switching."""

import logging
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


class Environment(StrEnum):
    PRODUCTION = "production"
    TESTNET = "testnet"


@dataclass(frozen=True)
class EnvConfig:
    """Configuration for a Deribit environment."""

    ws_url: str
    http_url: str


ENV_CONFIGS: dict[Environment, EnvConfig] = {
    Environment.PRODUCTION: EnvConfig(
        ws_url="wss://www.tibired.com/ws/api/v2",
        http_url="https://www.tibired.com/api/v2",
    ),
    Environment.TESTNET: EnvConfig(
        ws_url="wss://test.deribit.com/ws/api/v2",
        http_url="https://test.deribit.com/api/v2",
    ),
}

PRODUCTION_ENDPOINTS: dict[str, EnvConfig] = {
    "tibired": EnvConfig(
        ws_url="wss://www.tibired.com/ws/api/v2",
        http_url="https://www.tibired.com/api/v2",
    ),
    "deribit": EnvConfig(
        ws_url="wss://www.deribit.com/ws/api/v2",
        http_url="https://www.deribit.com/api/v2",
    ),
}


class EnvManager:
    """Manages environment switching between production and testnet."""

    def __init__(
        self,
        initial_env: Environment = Environment.TESTNET,
        allow_live_trading: bool = False,
    ) -> None:
        self._env = initial_env
        self._allow_live_trading = allow_live_trading
        self._production_endpoint: str = "tibired"

    @property
    def current_env(self) -> Environment:
        return self._env

    @property
    def production_endpoint(self) -> str:
        return self._production_endpoint

    def set_production_endpoint(self, name: str) -> None:
        """Set the production endpoint. Validates name is in PRODUCTION_ENDPOINTS."""
        if name not in PRODUCTION_ENDPOINTS:
            raise ValueError(
                f"Unknown production endpoint '{name}'. "
                f"Valid options: {list(PRODUCTION_ENDPOINTS.keys())}"
            )
        old = self._production_endpoint
        self._production_endpoint = name
        logger.info("Production endpoint switched: %s → %s", old, name)

    @property
    def config(self) -> EnvConfig:
        if self._env == Environment.PRODUCTION:
            return PRODUCTION_ENDPOINTS[self._production_endpoint]
        return ENV_CONFIGS[self._env]

    @property
    def ws_url(self) -> str:
        return self.config.ws_url

    @property
    def http_url(self) -> str:
        return self.config.http_url

    @property
    def allow_live_trading(self) -> bool:
        return self._allow_live_trading

    def is_production(self) -> bool:
        return self._env == Environment.PRODUCTION

    def set_env(self, env: Environment) -> None:
        """Switch environment. Caller is responsible for reconnecting the client."""
        old = self._env
        self._env = env
        logger.info("Environment switched: %s → %s", old, env)

    def set_allow_live_trading(self, allow: bool) -> None:
        self._allow_live_trading = allow
        logger.info("Live trading %s", "enabled" if allow else "disabled")

    def check_trading_allowed(self) -> None:
        """Raise if trading is not allowed in current environment."""
        if self.is_production() and not self._allow_live_trading:
            raise PermissionError(
                "Live trading is disabled. Set allow_live_trading=True to trade on production."
            )
