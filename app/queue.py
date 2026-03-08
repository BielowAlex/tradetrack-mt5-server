import os
from datetime import datetime
from typing import Any, Dict, Optional

from redis import Redis
from rq import Queue
from rq.job import Job

from .models import Mt5GetTradesRequest, Mt5TestConnectResponse
from .mt5_client import fetch_deals, Mt5Credentials, Mt5ConnectionError


REDIS_URL = "redis://localhost:6379/0"
QUEUE_NAME_PREFIX = "mt5_trades"
ACCOUNT_TERMINAL_KEY_PREFIX = "mt5:account"
ACCOUNT_TERMINAL_TTL_SEC = 86400  # 1 day

_redis: Redis | None = None
_queues_num: int | None = None


def _queues_count() -> int:
	global _queues_num
	if _queues_num is None:
		_queues_num = max(1, int(os.environ.get("MT5_QUEUES_NUM", "1")))
	return _queues_num


def get_redis() -> Redis:
	"""
	Single shared Redis connection (pool). Reused across enqueue/job-status to avoid
	per-request connection overhead.
	"""
	global _redis
	if _redis is None:
		url = os.environ.get("REDIS_URL", REDIS_URL)
		_redis = Redis.from_url(url, decode_responses=False)
	return _redis


def _account_key(login: int, server: str) -> str:
	normalized = (server or "").strip() or "_"
	return f"{login}:{normalized}"


def get_queue_index_for_account(login: int, server: str) -> int:
	"""Resolve which queue (terminal) should serve this account. Uses Redis mapping if set."""
	conn = get_redis()
	key = f"{ACCOUNT_TERMINAL_KEY_PREFIX}:{_account_key(login, server)}"
	stored = conn.get(key)
	if stored is not None:
		try:
			return int(stored) % _queues_count()
		except (ValueError, TypeError):
			pass
	return hash(_account_key(login, server)) % _queues_count()


def set_account_terminal(login: int, server: str, queue_index: int) -> None:
	"""Remember that this account was successfully served by this terminal (queue)."""
	conn = get_redis()
	key = f"{ACCOUNT_TERMINAL_KEY_PREFIX}:{_account_key(login, server)}"
	conn.setex(key, ACCOUNT_TERMINAL_TTL_SEC, str(queue_index))


def get_queue(queue_index: int | None = None) -> Queue:
	"""Get queue by index (0..N-1). If index is None, uses first queue (default)."""
	n = _queues_count()
	idx = 0 if queue_index is None else (queue_index % n)
	name = f"{QUEUE_NAME_PREFIX}_{idx}"
	return Queue(name, connection=get_redis())


def enqueue_trades_job(payload: Mt5GetTradesRequest) -> str:
	"""
	Enqueue a job to fetch MT5 trades. Returns job_id.
	Account is routed to the same terminal (queue) as before when known.
	"""
	idx = get_queue_index_for_account(payload.login, payload.server)
	q = get_queue(idx)
	job: Job = q.enqueue(
		run_trades_sync,
		payload.login,
		payload.password,
		payload.server,
		payload.from_timestamp,
		payload.to_timestamp,
	)
	return job.id


def enqueue_connect_job(creds: Mt5Credentials) -> str:
	"""
	Enqueue a job that only validates MT5 credentials (test-connect).
	Account is routed to the same terminal (queue) when known.
	"""
	idx = get_queue_index_for_account(creds.login, creds.server)
	q = get_queue(idx)
	job: Job = q.enqueue(
		run_test_connect,
		creds.login,
		creds.password,
		creds.server,
	)
	return job.id


def run_trades_sync(
	login: int,
	password: str,
	server: str,
	from_ts: Optional[datetime],
	to_ts: Optional[datetime],
) -> Dict[str, Any]:
	"""
	Worker function executed by RQ.
	MT5_PATH (env) — шлях до terminal64.exe portable-інстансу для цього воркера.
	MT5_QUEUE_INDEX (env) — індекс черги (терміналу); після успіху зберігається для цього акаунта.
	"""
	creds = Mt5Credentials(login=login, password=password, server=server)
	mt5_path = os.environ.get("MT5_PATH") or None
	deals = fetch_deals(creds, from_ts, to_ts, mt5_path=mt5_path)
	result = {
		"ok": True,
		"deals_count": len(deals),
		"deals": [d.model_dump() for d in deals],
	}
	queue_idx = os.environ.get("MT5_QUEUE_INDEX")
	if queue_idx is not None:
		try:
			set_account_terminal(login, server, int(queue_idx))
		except (ValueError, TypeError):
			pass
	return result


def run_test_connect(
	login: int,
	password: str,
	server: str,
) -> Dict[str, Any]:
	"""
	Worker function for credential validation.
	MT5_PATH (env) — шлях до terminal64.exe portable-інстансу для цього воркера.
	MT5_QUEUE_INDEX (env) — після успішного connect зберігається прив'язка акаунт -> термінал.
	"""
	creds = Mt5Credentials(login=login, password=password, server=server)
	mt5_path = os.environ.get("MT5_PATH") or None
	try:
		deals = fetch_deals(creds, mt5_path=mt5_path)
		resp = Mt5TestConnectResponse(
			ok=True,
			message="Connected successfully",
			deals_count=len(deals),
			sample_deals=[d.model_dump() for d in deals[:5]],
		)
		queue_idx = os.environ.get("MT5_QUEUE_INDEX")
		if queue_idx is not None:
			try:
				set_account_terminal(login, server, int(queue_idx))
			except (ValueError, TypeError):
				pass
	except Mt5ConnectionError as e:
		resp = Mt5TestConnectResponse(
			ok=False,
			message=str(e),
			deals_count=0,
			sample_deals=[],
		)
	return resp.model_dump()


def get_job_status(job_id: str) -> Dict[str, Any]:
	"""
	Read job status/result from Redis. Safe to call from API.
	"""
	job = Job.fetch(job_id, connection=get_redis())

	status = job.get_status()
	base: Dict[str, Any] = {"job_id": job.id, "status": status}

	if status == "failed":
		base["error"] = str(job.exc_info) if job.exc_info else "Job failed"
	elif status == "finished":
		base["result"] = job.result

	return base

