"""
Runtime risk guards for the baseline miner.

These run once at forward-module import time (i.e., once per miner start)
and surface network/risk configuration prominently in the miner logs.
Heavy guards (wallet balance, registration cost) live in run_miner.sh where
btcli is available before the Python process starts.
"""
import logging

logger = logging.getLogger(__name__)

_guard_ran = False


def startup_risk_check(is_mainnet: bool, risk_enabled: bool, min_balance_tao: float) -> None:
    """
    Log risk configuration once at miner startup.

    Emits a prominent WARNING when running on mainnet so it's
    impossible to miss in pm2 logs. No-ops on subsequent calls.
    """
    global _guard_ran
    if _guard_ran:
        return
    _guard_ran = True

    network_label = "MAINNET (finney)" if is_mainnet else "testnet"

    if is_mainnet:
        logger.warning("=" * 60)
        logger.warning("  NETWORK: %s — real TAO is at stake", network_label)
        logger.warning("  RISK_LIMITS_ENABLED: %s", risk_enabled)
        logger.warning("  MIN_BALANCE_TAO: %.4f", min_balance_tao)
        logger.warning("=" * 60)
    else:
        logger.info(
            "Network: %s | risk_limits=%s | min_balance=%.4f τ",
            network_label,
            risk_enabled,
            min_balance_tao,
        )
