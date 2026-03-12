import sys
import os


try:
    import flask_mail
except ModuleNotFoundError:
    print(
        "\nERROR: flask_mail is not installed.\n",
        file=sys.stderr,
    )
    sys.exit(1)

from app import create_app
from app.services.sla_monitor import start_sla_monitor

# Create the Flask app instance using  factory
app = create_app()

if __name__ == '__main__':
    start_sla_monitor(app)
    app.run(debug=True, use_reloader=False, port=5000)