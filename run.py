"""
Запуск MT5 Backend через Hypercorn (стабільний ASGI-сервер для Windows та 24/7).
Використання: python run.py
"""
import asyncio

from hypercorn.asyncio import serve
from hypercorn.config import Config

from app.main import app

if __name__ == "__main__":
    config = Config()
    config.bind = ["0.0.0.0:8000"]
    config.keep_alive_timeout = 0  # уникаємо "Invalid HTTP request" на Windows
    asyncio.run(serve(app, config))
