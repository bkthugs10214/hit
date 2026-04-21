"""
setup.py — maps the src/ directory to the precog_baseline_miner package.

After running `pip install -e .` from the project root, all modules under src/
become importable as `precog_baseline_miner.*`, e.g.:

    from precog_baseline_miner.data.binance_client import fetch_candles
    from precog_baseline_miner.forecast.baseline import compute_point_forecast
"""
from setuptools import setup

# Explicit package list with src/ directory mapping.
# This allows src/data/binance_client.py to be imported as
# precog_baseline_miner.data.binance_client, etc.
SUBPACKAGES = ["data", "features", "forecast", "miner", "eval", "utils", "risk"]

packages = ["precog_baseline_miner"] + [
    f"precog_baseline_miner.{sub}" for sub in SUBPACKAGES
]
# Nested sub-packages registered separately (dot-name ≠ slash-path)
packages.append("precog_baseline_miner.data.sentiment")

package_dir = {"precog_baseline_miner": "src"}
package_dir.update({
    f"precog_baseline_miner.{sub}": f"src/{sub}"
    for sub in SUBPACKAGES
})
package_dir["precog_baseline_miner.data.sentiment"] = "src/data/sentiment"

setup(
    name="precog-baseline-miner",
    version="0.1.0",
    packages=packages,
    package_dir=package_dir,
    python_requires=">=3.9,<3.12",
    install_requires=[
        "requests>=2.32",
        "pandas>=2.2",
        "numpy>=1.26",
    ],
    extras_require={
        "dev": ["pytest>=8", "pytest-asyncio>=0.23"],
    },
)
