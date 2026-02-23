"""Main UI Blueprint — serves the SPA shell and favicon."""
import io
import os
from flask import Blueprint, current_app, render_template, session, send_file
from helpers.offline_queue import get_logo, get_base_path, load_queue

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    current_store = session.get('store', 'Carimas #1')
    logo_data = get_logo(current_store)
    has_pending = len(load_queue()) > 0
    template = 'main.html' if session.get('logged_in') else 'login.html'
    version = current_app.config.get('APP_VERSION', '')
    return render_template(template, logo=logo_data, pending=has_pending, version=version)


@bp.route('/favicon.ico')
def favicon():
    """Serve logo.png as the site favicon (eliminates 404 on every page load)."""
    logo_path = os.path.join(get_base_path(), 'logo.png')
    if os.path.exists(logo_path):
        with open(logo_path, 'rb') as fh:
            return send_file(io.BytesIO(fh.read()), mimetype='image/png')
    return '', 204
