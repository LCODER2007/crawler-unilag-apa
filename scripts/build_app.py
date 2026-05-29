import os
import sys

sys.path.insert(0, ".")

APP = """import os,csv,io,subprocess,threading,re,logging
from flask import Flask,render_template,jsonify,send_file,request,Response
from flask_socketio import SocketIO
from uraas.config import config
from uraas.analytics.engine import analytics
from uraas.database import SessionLocal,Item,File,Author,Community,Collection
from uraas.utils.docid_generator import docid_generator
from sqlalchemy import func,extract,desc,or_

app = Flask(__name__)
app.config["SECRET_KEY"] = config.DASHBOARD_SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*")
logger = logging.getLogger(__name__)
crawler_process = None
crawler_lock = threading.Lock()
docid_crawler_process = None
docid_crawler_lock = threading.Lock()
"""

open("uraas/dashboard/app.py", "w", encoding="utf-8").write(APP)
print("wrote", len(APP), "chars")
