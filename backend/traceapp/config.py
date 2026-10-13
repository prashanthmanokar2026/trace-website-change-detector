import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')
DATA = Path(os.getenv('TRACE_DATA', str(ROOT / 'data')))
BASE_URL = os.getenv('TRACE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
PROXY = os.getenv('TRACE_PROXY', 'http://127.0.0.1:8899')
OWNER_HASH = os.getenv('TRACE_OWNER_HASH', '')
RETENTION = max(5, int(os.getenv('TRACE_RETENTION', '50')))
DOMAIN_DELAY = max(5, int(os.getenv('TRACE_DOMAIN_DELAY', '15')))
