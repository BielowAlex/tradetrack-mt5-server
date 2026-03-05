"""
Налаштування логів: файл logs/mt5-backend.log + консоль.
"""
import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "mt5-backend.log"
FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
	LOG_DIR.mkdir(parents=True, exist_ok=True)
	root = logging.getLogger()
	root.setLevel(level)
	# прибираємо дублі хендлерів при повторному виклику
	for h in list(root.handlers):
		root.removeHandler(h)

	file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
	file_handler.setLevel(level)
	file_handler.setFormatter(logging.Formatter(FORMAT, datefmt=DATE_FMT))

	console_handler = logging.StreamHandler(sys.stderr)
	console_handler.setLevel(level)
	console_handler.setFormatter(logging.Formatter(FORMAT, datefmt=DATE_FMT))

	root.addHandler(file_handler)
	root.addHandler(console_handler)

	logging.getLogger("app").info("Logging configured: %s", LOG_FILE)
