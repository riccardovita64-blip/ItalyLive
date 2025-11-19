import os
import random
from flask import Flask, render_template, request, redirect, url_for, flash, Response
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import cv2

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chiave_segreta_default_per_sviluppo')

# --- CONFIGURAZIONE DATABASE CLOUD-READY ---
# Se siamo online (es. su Render), usa il database PostgreSQL fornito dall'ambiente.
# Se siamo sul PC, usa il file database.db locale.
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*") # Permette connessioni da qualsiasi sito
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELLO UTENTE (Semplificato senza conferma email) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    color = db.Column(db.String(20), default='#ffffff')
    # is_streamer: in futuro servirà per decidere chi può trasmettere
    is_streamer = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- GESTIONE CAMERA (Webcam Locale) ---
streaming_active = False
camera = None

def generate_frames():
    global camera
    while streaming_active:
        if camera is None: break
        success, frame = camera.read()
        if not success: break
        else:
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

# --- NO CACHE HEADERS ---
@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# --- ROTTE ---

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=current_user.username, is_live=streaming_active)

@app.route('/video_feed')
def video_feed():
    if streaming_active:
        return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
    return "", 204

@app.route('/toggle_stream', methods=['POST'])
@login_required
def toggle_stream():
    global streaming_active, camera
    if not streaming_active:
        try:
            # Nota: Questo funzionerà solo se il server ha una webcam fisica attaccata!
            camera = cv2.VideoCapture(0)
            if not camera.isOpened():
                flash("Nessuna webcam trovata sul server (normale se sei in cloud).", "error")
                return redirect(url_for('index'))
            streaming_active = True
            socketio.emit('stream_status', {'status': 'live'})
        except Exception as e:
            flash(f"Errore webcam: {e}", "error")
    else:
        streaming_active = False
        if camera:
            camera.release()
            camera = None
        socketio.emit('stream_status', {'status': 'offline'})
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username')
        password = request.form.get('password')

        if action == 'register':
            if User.query.filter_by(username=username).first():
                flash('Username già esistente', 'error')
            else:
                new_user = User(
                    username=username,
                    password=generate_password_hash(password, method='pbkdf2:sha256'),
                    color=random.choice(['#ef4444', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6'])
                )
                db.session.add(new_user)
                db.session.commit()
                login_user(new_user) # Login automatico dopo registrazione
                return redirect(url_for('index'))

        elif action == 'login':
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
                login_user(user)
                return redirect(url_for('index'))
            else:
                flash('Credenziali errate', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- SOCKETS ---
@socketio.on('send_message')
def handle_message(data):
    if current_user.is_authenticated:
        emit('new_message', {
            'username': current_user.username, 
            'message': data['message'], 
            'color': current_user.color
        }, broadcast=True)

@socketio.on('send_tip')
def handle_tip(data):
    if current_user.is_authenticated:
        emit('new_tip', {
            'username': current_user.username, 
            'amount': data['amount']
        }, broadcast=True)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # debug=False per produzione, host 0.0.0.0 per essere visibile
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)