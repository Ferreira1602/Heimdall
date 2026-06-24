"""wsgi.py — entrypoint WSGI para mod_wsgi/Apache."""
import sys
sys.path.insert(0, "/var/www/heimdall")

from app import create_app

application = create_app("production")
app = application

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=8000)
