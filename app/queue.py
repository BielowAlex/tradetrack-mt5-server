import os
from datetime import datetime
from typing import Any, Dict, Optional

from redis import Redis
from rq import Queue
from rq.job import Job

from .models import Mt5GetTradesRequest, Mt5TestConnectResponse
from .mt5_client import fetch_deals, Mt5Credentials, Mt5ConnectionError


REDIS_URL = "redis://localhost:6379/0"
QUEUE_NAME = "mt5_trades"

_redis: Redis | None = None


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


def get_queue() -> Queue:
	return Queue(QUEUE_NAME, connection=get_redis())


def enqueue_trades_job(payload: Mt5GetTradesRequest) -> str:
	"""
	Enqueue a job to fetch MT5 trades. Returns job_id.
	Note: jobs are executed by an RQ worker process.
	"""
	q = get_queue()
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
	This проходить через той самий воркер/чергу, щоб уникнути паралельних звернень до MT5.
	"""
	q = get_queue()
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
	"""
	creds = Mt5Credentials(login=login, password=password, server=server)
	mt5_path = os.environ.get("MT5_PATH") or None
	deals = fetch_deals(creds, from_ts, to_ts, mt5_path=mt5_path)
	return {
		"ok": True,
		"deals_count": len(deals),
		"deals": [d.model_dump() for d in deals],
	}


def run_test_connect(
	login: int,
	password: str,
	server: str,
) -> Dict[str, Any]:
	"""
	Worker function for credential validation.
	MT5_PATH (env) — шлях до terminal64.exe portable-інстансу для цього воркера.
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
	q = get_queue()
	job = Job.fetch(job_id, connection=q.connection)

	status = job.get_status()
	base: Dict[str, Any] = {"job_id": job.id, "status": status}

	if status == "failed":
		base["error"] = str(job.exc_info) if job.exc_info else "Job failed"
	elif status == "finished":
		base["result"] = job.result

	return base

