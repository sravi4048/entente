import os
import tempfile

# Must run before the app is imported anywhere.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SCHEDULER_INTERVAL_SECONDS", "3600")
os.environ.setdefault("STATIC_DIR", "/nonexistent")
