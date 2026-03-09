"""
Broker discovery для MT5: якщо сервер не в servers.dat, MT5 робить discovery через CLI.

MT5 Python API не робить broker discovery — сервер має бути вже в списку.
Рішення: запустити terminal64.exe з /portable /login /password /server —
MT5 сам знайде брокера в MetaQuotes-директорії, додасть у servers.dat, підключиться.
Після цього Python initialize() працює.
"""
import subprocess
import time
from typing import Optional

# Час очікування discovery + підключення (секунди)
DISCOVERY_WAIT_SEC = 10
# Таймаут на завершення процесу після wait
TERMINATE_TIMEOUT_SEC = 5


def ensure_server_known(
	mt5_path: str,
	login: int,
	password: str,
	server: str,
	wait_sec: float = DISCOVERY_WAIT_SEC,
) -> None:
	"""
	Запускає MT5 з CLI-параметрами, щоб він зробив broker discovery і додав сервер у servers.dat.

	MT5 при старті з /login /password /server:
	- робить запит до MetaQuotes broker directory
	- завантажує IP, порт, company name
	- записує в config/servers.dat
	- підключається до рахунку

	Після цього mt5.initialize(path=..., login=..., password=..., server=...) працює.

	Обов'язково /portable — інакше всі інстанси пишуть в AppData і конфліктують.
	"""
	path = (mt5_path or "").strip()
	if not path:
		return

	server = (server or "").strip()
	if not server:
		return

	args = [
		path,
		"/portable",
		f"/login:{login}",
		f"/password:{password}",
		f"/server:{server}",
	]

	# Не використовуємо CREATE_NO_WINDOW — MT5 може потребувати вікно для коректної ініціалізації.
	# Вікно зʼявиться на ~10 с під час discovery, потім закриється.
	proc = subprocess.Popen(
		args,
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
	)

	try:
		time.sleep(wait_sec)
	finally:
		# Завершуємо процес — servers.dat вже оновлено
		try:
			proc.terminate()
			proc.wait(timeout=TERMINATE_TIMEOUT_SEC)
		except (subprocess.TimeoutExpired, ProcessLookupError):
			try:
				proc.kill()
		except ProcessLookupError:
			pass
