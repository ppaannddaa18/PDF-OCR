import logging
from pathlib import Path
from datetime import datetime


def setup_logger():
    Path("logs").mkdir(exist_ok=True)
    log_file = f"logs/app_{datetime.now().strftime('%Y%m%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
