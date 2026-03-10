import sys
import os


try:
    import flask_mail
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

# Create the Flask app instance using  factory
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, port=5000)