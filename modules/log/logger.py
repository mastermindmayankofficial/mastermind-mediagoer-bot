import logging
from collections import deque
from datetime import datetime, timedelta

# In-memory ring buffer holding up to 2000 log entries in RAM
LOG_BUFFER = deque(maxlen=2000)

class InMemoryLogHandler(logging.Handler):
    """Custom handler that catches log records and stores them in RAM."""
    def emit(self, record):
        try:
            msg = self.format(record)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            LOG_BUFFER.append((datetime.now(), f"[{timestamp}] {msg}\n"))
        except Exception:
            self.handleError(record)

def setup_in_memory_logger():
    """Attaches the memory handler to Python's root logger."""
    root_logger = logging.getLogger()
    if not any(isinstance(h, InMemoryLogHandler) for h in root_logger.handlers):
        handler = InMemoryLogHandler()
        formatter = logging.Formatter('%(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

def get_logs_by_count(n: int = 10):
    """Retrieves the last N logs from memory."""
    if not LOG_BUFFER:
        return "No logs captured in memory yet."
    lines = [item[1] for item in LOG_BUFFER]
    selected = lines[-n:] if len(lines) >= n else lines
    return "".join(selected)

def get_logs_by_time(minutes: int = 10):
    """Retrieves logs from memory within the last N minutes."""
    if not LOG_BUFFER:
        return f"No logs captured in memory within the last {minutes} minutes."
    cutoff_time = datetime.now() - timedelta(minutes=minutes)
    filtered_lines = [item[1] for item in LOG_BUFFER if item[0] >= cutoff_time]
    if not filtered_lines:
        return f"No logs found in memory within the last {minutes} minutes."
    return "".join(filtered_lines)
