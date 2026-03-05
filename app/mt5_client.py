import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

import MetaTrader5 as mt5

# Очікування готовності історії після логіну: спроби з інтервалом, макс. час
HISTORY_RETRY_INTERVAL_SEC = 0.25
HISTORY_MAX_RETRIES = 6  # макс. ~1.5 с загалом

from .models import Mt5Credentials, Mt5Deal


class Mt5ConnectionError(Exception):
	"""Raised when initialization or login to MT5 fails."""


@contextmanager
def mt5_session(creds: Mt5Credentials, timeout_ms: int = 30_000, path: Optional[str] = None):
	"""
	Context manager that mirrors bridge behaviour.
	path: шлях до terminal64.exe portable-інстансу (напр. C:\\Program Files\\mt5-instance1\\terminal64.exe).
	"""
	# Скидаємо попередній стан, щоб термінал не залипав на невдалому акаунті
	mt5.shutdown()

	init_kwargs = {
		"login": creds.login,
		"password": creds.password,
		"server": creds.server.strip(),
		"timeout": timeout_ms,
	}

	if path and path.strip():
		ok = mt5.initialize(path.strip(), **init_kwargs)
	else:
		ok = mt5.initialize(**init_kwargs)
	if not ok:
		err = mt5.last_error()
		mt5.shutdown()
		raise Mt5ConnectionError(f"MT5 init failed: {err}")

	info = mt5.account_info()
	if info is not None and getattr(info, "login", None) == creds.login:
		try:
			yield
		finally:
			mt5.shutdown()
		return

	# initialize() пройшов, але підключений інший рахунок — пробуємо explicit login()
	if not mt5.login(creds.login, password=creds.password, server=creds.server):
		err = mt5.last_error()
		mt5.shutdown()
		raise Mt5ConnectionError(f"MT5 login failed: {err}")

	try:
		yield
	finally:
		mt5.shutdown()


def fetch_deals(
	creds: Mt5Credentials,
	from_ts: Optional[datetime] = None,
	to_ts: Optional[datetime] = None,
	mt5_path: Optional[str] = None,
) -> List[Mt5Deal]:
	"""
	Отримати угоди з історії MT5 і замапити в Pydantic-моделі.
	mt5_path: шлях до terminal64.exe portable-інстансу (для воркера з MT5_PATH).
	"""
	if to_ts is None:
		to_ts = datetime.now()
	if from_ts is None:
		from_ts = to_ts - timedelta(days=30)

	with mt5_session(creds, path=mt5_path):
		raw_deals: Optional[Iterable] = None
		for _ in range(HISTORY_MAX_RETRIES):
			raw_deals = mt5.history_deals_get(from_ts, to_ts)
			if raw_deals is not None:
				break
			time.sleep(HISTORY_RETRY_INTERVAL_SEC)

	if raw_deals is None:
		return []

	deals: List[Mt5Deal] = []
	for d in raw_deals:
		try:
			deals.append(
				Mt5Deal(
					ticket=getattr(d, "ticket", 0),
					order=getattr(d, "order", 0),
					position_id=getattr(d, "position_id", 0),
					time=datetime.fromtimestamp(getattr(d, "time", 0)),
					symbol=getattr(d, "symbol", ""),
					volume=float(getattr(d, "volume", 0.0)),
					price=float(getattr(d, "price", 0.0)),
					profit=float(getattr(d, "profit", 0.0)),
					comment=getattr(d, "comment", "") or None,
				)
			)
		except Exception:
			# If mapping of a single deal fails, skip it and continue
			continue

	return deals

