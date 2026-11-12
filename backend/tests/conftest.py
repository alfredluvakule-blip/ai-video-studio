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
os.environ["GEMINI_API_KEY"] = ""
os.environ["POLLINATIONS"] = "false"  # tests never call the real service; test_providers mocks it
os.environ["PIPER_AUTO_DOWNLOAD"] = "false"
os.environ["OLLAMA_URL"] = "http://127.0.0.1:9"  # nothing listens here
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
