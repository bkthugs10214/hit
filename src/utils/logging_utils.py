"""
Logging setup for standalone (non-Bittensor) usage.

Inside the Precog miner, bittensor.logging is used automatically.
This module is only needed for the smoke test (src/main.py) and unit tests.
"""
import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger for CLI / smoke-test usage."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
