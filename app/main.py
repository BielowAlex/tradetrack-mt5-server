from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .models import (
	Mt5Credentials,
	Mt5GetTradesRequest,
	Mt5GetTradesResponse,
	Mt5TestConnectResponse,
)
from .mt5_client import Mt5ConnectionError, fetch_deals
from .queue import enqueue_trades_job, enqueue_connect_job, get_job_status

app = FastAPI(title="MT5 Backend API", version="0.1.0")

# Для тестів можна дозволити всі origin; у проді краще обмежити доменами фронтенду
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.get("/health", summary="Health check")
def health_check():
	return {"status": "ok"}


@app.post("/mt5/test-connect", response_model=Mt5TestConnectResponse)
def test_connect(creds: Mt5Credentials):
	"""
	Коротке підключення до MT5, щоб впевнитись що логін/сервер робочі.
	Повертає кількість угод за останні 7 днів і до 5 прикладів.
	"""
	try:
		deals = fetch_deals(creds)
	except Mt5ConnectionError as e:
		raise HTTPException(status_code=400, detail=str(e))
	except Exception as e:
		raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e

	sample = deals[:5]

	return Mt5TestConnectResponse(
		ok=True,
		message="Connected successfully",
		deals_count=len(deals),
		sample_deals=[d.model_dump() for d in sample],
	)


@app.post("/mt5/get-trades", response_model=Mt5GetTradesResponse)
def get_trades(payload: Mt5GetTradesRequest):
	"""
	One-shot запит: підключитись до MT5, отримати історію угод, відключитись.
	За замовчуванням повертає останні 30 днів.
	"""
	creds = Mt5Credentials(
		login=payload.login,
		password=payload.password,
		server=payload.server,
	)

	try:
		deals = fetch_deals(creds, payload.from_timestamp, payload.to_timestamp)
	except Mt5ConnectionError as e:
		raise HTTPException(status_code=400, detail=str(e))
	except Exception as e:
		raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e

	return Mt5GetTradesResponse(
		ok=True,
		message=f"Fetched {len(deals)} deals",
		deals=deals,
	)


@app.post("/mt5/enqueue-trades", summary="Поставити задачу на отримання угод у чергу")
def enqueue_trades(payload: Mt5GetTradesRequest):
	"""
	Ставит задачу в Redis/RQ-чергу. Повертає job_id, який можна опитувати.
	Реальний виклик MT5 виконає окремий worker-процес.
	"""
	job_id = enqueue_trades_job(payload)
	return {"job_id": job_id, "status": "queued"}


@app.post("/mt5/enqueue-connect", summary="Поставити задачу на перевірку конекту в чергу")
def enqueue_connect(creds: Mt5Credentials):
	"""
	Ставит задачу на test-connect у Redis/RQ-чергу. Повертає job_id.
	Це безпечний спосіб перевіряти креденшіали, якщо багато юзерів конектяться одночасно.
	"""
	job_id = enqueue_connect_job(creds)
	return {"job_id": job_id, "status": "queued"}


@app.get("/mt5/job-status/{job_id}", summary="Статус задачі з черги")
def job_status(job_id: str):
	"""
	Повертає статус задачі: queued, started, finished, failed.
	Якщо finished — повертає result з кількістю угод і масивом deals.
	"""
	try:
		status = get_job_status(job_id)
	except Exception as e:
		raise HTTPException(status_code=404, detail=f"Job not found: {e}") from e

	return status

