"""
Запуск MT5 Backend через Hypercorn (стабільний ASGI-сервер для Windows та 24/7).
Логи: консоль + файл logs/mt5-backend.log
Використання: python run.py
"""
import asyncio

from hypercorn.asyncio import serve
from hypercorn.config import Config

from app.logging_config import setup_logging
from app.main import app

if __name__ == "__main__":
    setup_logging()
    config = Config()
    config.bind = ["0.0.0.0:8000"]
    config.workers = 3
    config.worker_connections = 100
    config.backlog = 2048
    config.keep_alive_timeout = 0  # уникаємо "Invalid HTTP request" на Windows
    asyncio.run(serve(app, config))
