import time
from contextlib import contextmanager
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import MetaTrader5 as mt5

# Очікування готовності історії після логіну: спроби з інтервалом, макс. час
HISTORY_RETRY_INTERVAL_SEC = 0.25
HISTORY_MAX_RETRIES = 6  # макс. ~1.5 с загалом

# MT5 deal entry/type enums (as in bridge; use dict keys from _asdict())
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2
DEAL_ENTRY_OUT_BY = 3
DEAL_ENTRY_CLOSING = (DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY)  # 1, 2, 3 — лише закриття
DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1

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

	# Як у bridge: перетворюємо на dict через _asdict(), щоб надійно читати "entry"/"type"
	deals_dicts: List[dict] = []
	for d in raw_deals:
		try:
			deals_dicts.append(d._asdict() if hasattr(d, "_asdict") else dict(d))
		except Exception:
			continue

	# Тільки BUY/SELL (type 0/1)
	trade_dicts = [d for d in deals_dicts if d.get("type") in (DEAL_TYPE_BUY, DEAL_TYPE_SELL)]
	if not trade_dicts:
		return []

	# Group by position_id: list of (time_unix, entry, type, deal_dict)
	by_position: Dict[int, List[Tuple[int, int, int, dict]]] = defaultdict(list)
	for d in trade_dicts:
		try:
			entry = d.get("entry", DEAL_ENTRY_IN)
			deal_type = d.get("type", DEAL_TYPE_BUY)
			t_val = d.get("time")
			if hasattr(t_val, "timestamp"):
				t = int(t_val.timestamp())
			else:
				t = int(t_val) if t_val is not None else 0
			pid = d.get("position_id") or d.get("ticket", 0)
			try:
				pid = int(pid)
			except (TypeError, ValueError):
				pid = int(d.get("ticket", 0))
			by_position[pid].append((t, entry, deal_type, d))
		except Exception:
			continue

	# Лише закриття (entry in 1,2,3) — як у bridge DEAL_ENTRY_CLOSING
	deals: List[Mt5Deal] = []
	for position_id, group in by_position.items():
		if position_id == 0:
			continue
		# Час відкриття: найраніший IN (entry==0) по цій позиції
		time_open_unix: Optional[int] = None
		for t, entry, _, _ in group:
			if entry == DEAL_ENTRY_IN:
				if time_open_unix is None or t < time_open_unix:
					time_open_unix = t
		# Один запис на кожну угоду закриття (OUT/INOUT/OUT_BY)
		for t_unix, entry, deal_type, d in group:
			if entry not in DEAL_ENTRY_CLOSING or deal_type not in (DEAL_TYPE_BUY, DEAL_TYPE_SELL):
				continue
			open_ts = time_open_unix if time_open_unix is not None else t_unix
			try:
				comm = d.get("commission")
				sw = d.get("swap")
				deals.append(
					Mt5Deal(
						ticket=int(d.get("ticket", 0)),
						position_id=position_id,
						symbol=str(d.get("symbol", "")).strip(),
						direction="SELL" if deal_type == DEAL_TYPE_SELL else "BUY",
						volume=float(d.get("volume", 0) or 0),
						price=float(d.get("price", 0) or 0),
						profit=float(d.get("profit", 0) or 0),
						time=int(t_unix),
						time_open=int(open_ts),
						commission=float(comm) if comm is not None else None,
						swap=float(sw) if sw is not None else None,
					)
				)
			except Exception:
				continue

	return deals

