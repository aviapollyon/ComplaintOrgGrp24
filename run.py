
# Entry point for running the Flask application
import sys
import os

# Guard: ensure flask_mail is available before anything else imports it.
# If using the system Python instead of the venv, provide a clear error.
try:
    import flask_mail  # noqa: F401
except ModuleNotFoundError:
    print(
        "\nERROR: flask_mail is not installed.\n"
        "Please run the server using the project's virtual environment:\n"
        r"  .\venv\Scripts\python.exe run.py"
        "\nor activate it first:\n"
        r"  .\venv\Scripts\Activate.ps1"
        "\n  python run.py\n",
        file=sys.stderr,
    )
    sys.exit(1)

from app import create_app

# Create the Flask app instance using the factory
app = create_app()

if __name__ == '__main__':
    # use_reloader=False avoids Flask spawning a second process that
    # also binds the port, which leaves zombie sockets when stopped.
    app.run(debug=True, use_reloader=False, port=5000)