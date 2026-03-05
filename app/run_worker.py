"""
Windows-сумісний RQ воркер: використовує TimerDeathPenalty замість UnixSignalDeathPenalty (SIGALRM),
щоб таймаути працювали без os.fork і signal.SIGALRM.
"""
from rq.worker import SimpleWorker
from rq.timeouts import TimerDeathPenalty


class WindowsSimpleWorker(SimpleWorker):
	"""SimpleWorker з таймаутами через threading.Timer (працює на Windows)."""
	death_penalty_class = TimerDeathPenalty
