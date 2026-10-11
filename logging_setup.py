import logging
from pathlib import Path

def setup_logging(level="INFO"):
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler("logs/trader.log", encoding="utf-8")],
    )
