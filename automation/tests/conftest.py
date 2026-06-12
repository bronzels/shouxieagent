"""
pytest 公共配置：路径、fixture、常量
"""
import sys
from pathlib import Path

# 确保 automation/ui-tars-server 在 sys.path
SERVER_DIR = Path(__file__).parent.parent / "ui-tars-server"
sys.path.insert(0, str(SERVER_DIR))

UITARS_SERVER = "http://192.168.3.14:8000"
UITARS_BASE_URL = f"{UITARS_SERVER}/v1"
