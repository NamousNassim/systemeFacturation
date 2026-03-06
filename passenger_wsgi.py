"""
WSGI entrypoint for cPanel Passenger.
Adjust `BASE_DIR` or virtualenv activation here if your app root differs.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Ensure project is on the Python path
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
