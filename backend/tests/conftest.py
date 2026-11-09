import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="studio-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["QUEUE_BACKEND"] = "inline"
os.environ["LLM_PROVIDER"] = "template"
os.environ["COMFYUI_URL"] = ""
os.environ["HF_TOKEN"] = ""
os.environ["OLLAMA_URL"] = "http://127.0.0.1:9"  # nothing listens here
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
