import time
from contextlib import contextmanager
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import MetaTrader5 as mt5

# Очікування готовності історії після логіну: спроби з інтервалом, макс. час
HISTORY_RETRY_INTERVAL_SEC = 0.25  # швидші повторні спроби
HISTORY_MAX_RETRIES = 25  # макс. ~6 с загалом при неуспіху
# якщо брокер повернув порожню історію — дати йому час підтягнути, повторити
HISTORY_EMPTY_RETRIES = 4
HISTORY_EMPTY_SLEEP_SEC = 1.2

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
		# Широкий діапазон, щоб мати IN-угоди для коректного time_open (як у bridge)
		from_ts = to_ts - timedelta(days=365)

	with mt5_session(creds, path=mt5_path):
		time.sleep(0.4)  # мінімальна пауза після логіну перед запитом історії
		raw_deals: Optional[Iterable] = None
		for _ in range(HISTORY_MAX_RETRIES):
			raw_deals = mt5.history_deals_get(from_ts, to_ts)
			if raw_deals is not None:
				break
			time.sleep(HISTORY_RETRY_INTERVAL_SEC)

		if raw_deals is not None and hasattr(raw_deals, "__len__") and len(raw_deals) == 0:
			for _ in range(HISTORY_EMPTY_RETRIES - 1):
				time.sleep(HISTORY_EMPTY_SLEEP_SEC)
				raw_deals = mt5.history_deals_get(from_ts, to_ts)
				if raw_deals is not None and hasattr(raw_deals, "__len__") and len(raw_deals) > 0:
					break

	if raw_deals is None:
		return []

	# Як у bridge: перетворюємо на dict через _asdict(), щоб надійно читати "entry"/"type"
	deals_dicts: List[dict] = []
	for d in raw_deals:
		try:
			deals_dicts.append(d._asdict() if hasattr(d, "_asdict") else dict(d))
		except Exception:
			continue

	def _entry_int(d: dict) -> int:
		"""Нормалізуємо entry: можливі ключі entry/Entry, значення int або string."""
		v = d.get("entry") if d.get("entry") is not None else d.get("Entry")
		if v is None:
			return DEAL_ENTRY_IN
		try:
			return int(v)
		except (TypeError, ValueError):
			return DEAL_ENTRY_IN

	def _time_unix(d: dict) -> int:
		t_val = d.get("time")
		if hasattr(t_val, "timestamp"):
			return int(t_val.timestamp())
		return int(t_val) if t_val is not None else 0

	# Тільки торгові угоди BUY/SELL (type 0/1); відкидаємо balance, credit тощо
	def _type_int(d: dict) -> int:
		v = d.get("type")
		if v is None:
			return -1
		try:
			return int(v)
		except (TypeError, ValueError):
			return -1

	trade_dicts = [d for d in deals_dicts if _type_int(d) in (DEAL_TYPE_BUY, DEAL_TYPE_SELL)]
	if not trade_dicts:
		return []

	# Як у bridge: по одній угоді на позицію (з найпізнішим часом), потім лише закриття (entry in 1,2,3)
	by_key: Dict[int, dict] = {}
	for d in trade_dicts:
		try:
			pid = d.get("position_id") or d.get("ticket", 0)
			try:
				pid = int(pid)
			except (TypeError, ValueError):
				pid = int(d.get("ticket", 0))
			if pid == 0:
				continue
			t = _time_unix(d)
			if pid not in by_key or t >= _time_unix(by_key[pid]):
				by_key[pid] = d
		except Exception:
			continue

	# Лише угоди з entry in (1, 2, 3) — явно відкидаємо IN (0) та будь-що інше
	closing_only = [
		(pid, d) for pid, d in by_key.items()
		if _entry_int(d) in DEAL_ENTRY_CLOSING
	]

	# Збираємо time_open: для кожної позиції шукаємо IN-угоду в повному списку
	all_by_pid: Dict[int, List[dict]] = defaultdict(list)
	for d in trade_dicts:
		try:
			pid = d.get("position_id") or d.get("ticket", 0)
			try:
				pid = int(pid)
			except (TypeError, ValueError):
				pid = int(d.get("ticket", 0))
			if pid != 0:
				all_by_pid[pid].append(d)
		except Exception:
			continue

	# Збираємо без дублікатів по ticket (один запис на угоду)
	seen_tickets: set = set()
	deals: List[Mt5Deal] = []
	for position_id, d in closing_only:
		try:
			entry = _entry_int(d)
			deal_type = _type_int(d)
			if entry not in DEAL_ENTRY_CLOSING or deal_type not in (DEAL_TYPE_BUY, DEAL_TYPE_SELL):
				continue
			ticket = int(d.get("ticket", 0))
			if ticket in seen_tickets:
				continue
			seen_tickets.add(ticket)
			t_unix = _time_unix(d)
			time_open_unix: Optional[int] = None
			for other in all_by_pid.get(position_id, []):
				if _entry_int(other) == DEAL_ENTRY_IN:
					ot = _time_unix(other)
					if time_open_unix is None or ot < time_open_unix:
						time_open_unix = ot
			open_ts = time_open_unix if time_open_unix is not None else t_unix
			comm = d.get("commission")
			sw = d.get("swap")
			deals.append(
				Mt5Deal(
					ticket=ticket,
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

