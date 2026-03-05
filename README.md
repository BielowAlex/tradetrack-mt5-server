# MT5 Backend (FastAPI)

Простий Python-сервер для підключення до MetaTrader 5 з VPS.

## Локальний запуск

1. Встанови Python 3.11+ на Windows.
2. Встанови залежності:

```bash
pip install -r requirements.txt
```

3. Переконайся, що на цій самій машині встановлено MetaTrader 5 і він може логінитись до потрібного брокера.

4. Запусти сервер:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Тест без Redis і воркерів (тільки API)

Можна тестувати **локально без інстансів** (без Redis, без RQ workers):

1. Запусти лише Uvicorn (крок 4 вище).
2. Відкрий Swagger: http://localhost:8000/docs
3. **Перевірка конекту:** `POST /mt5/test-connect` — тіло: `{"login": 12345, "password": "пароль", "server": "Broker-Server"}`
4. **Звичайний синк (угоди):** `POST /mt5/get-trades` — ті ж login/password/server; опційно `from_timestamp`, `to_timestamp` (ISO). Повертає лише **закриті** угоди (фільтр entry in 1,2,3, один запис на позицію, без дублікатів по ticket).

Ці два ендпоінти підключаються до MT5 напряму в поточному процессі (без черги). Для `enqueue-trades` та `enqueue-connect` потрібні Redis і воркери.

## Основні ендпоінти

- `POST /mt5/test-connect` — разовий конект до MT5 та повернення базової інформації про угоди.
- `POST /mt5/get-trades` — повернення списку угод за останній період (MVP).

Обидва ендпоінти виконують коротке підключення: `initialize → login → отримання даних → shutdown`.

## Черга задач (Redis + RQ)

Для асинхронної обробки запитів до MT5 використовуються Redis і RQ.

1. Запусти Redis (локально або в Docker):

```bash
docker run -d --name redis-mt5 -p 6379:6379 redis:7
```

2. Запусти RQ-воркер. **На Windows** обовʼязково використовуй наш клас (без `fork` і без `SIGALRM`):

```bash
python -m rq.cli worker --worker-class app.run_worker.WindowsSimpleWorker mt5_trades --url redis://localhost:6379/0
```

3. Запусти FastAPI-сервер:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

4. Тестування черги через Swagger (`/docs`):
- `POST /mt5/enqueue-trades` — поставити задачу в чергу, повертає `job_id`.
- `GET /mt5/job-status/{job_id}` — перевірити статус задачі й забрати результат, коли `status = finished`.

## Два portable-інстанси MT5 (два воркери)

Щоб обробляти задачі двома MT5 одночасно: скопіюй папку MT5 у дві папки (наприклад `C:\Program Files\mt5-instance1` і `C:\Program Files\mt-instance2`), кожен запускай як `terminal64.exe /portable`. Потім запусти **два** воркери з різним `MT5_PATH` (з каталогу `mt5-backend`):

**Термінал 1:**
```powershell
$env:MT5_PATH="C:\Program Files\mt5-instance1\terminal64.exe"
python -m rq.cli worker --worker-class app.run_worker.WindowsSimpleWorker mt5_trades --url redis://localhost:6379/0
```

**Термінал 2:**
```powershell
$env:MT5_PATH="C:\Program Files\mt-instance2\terminal64.exe"
python -m rq.cli worker --worker-class app.run_worker.WindowsSimpleWorker mt5_trades --url redis://localhost:6379/0
```

Задачі з черги розподіляться між двома воркерами.

