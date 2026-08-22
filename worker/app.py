from flask import Flask
from worker import main
import threading

app = Flask(__name__)

threading.Thread(target=main, daemon=True).start()

@app.route("/")
def health():
    return "Worker is running", 200