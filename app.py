import os
import random
import sys
import socket # 1. Importa socket

# --- FIX RETE: FORZA IPV4 ---
# Questo blocco costringe il server a ignorare IPv6 (che causa l'errore 101)
# e usare solo la connessione standard IPv4 verso Gmail.
def getaddrinfo(*args, **kwargs):
    res = socket._original_getaddrinfo(*args, **kwargs)
    return [r for r in res if r[0] == socket.AF_INET]

if not hasattr(socket, '_original_getaddrinfo'):
    socket._original_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = getaddrinfo
# ---------------------------

from flask import Flask, render_template, request, redirect, url_for, flash, Response
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
import cv2

def log(message):
    print(message, file=sys.stdout, flush=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chiave_segreta_default_per_sviluppo')
app.config['SECURITY_PASSWORD_SALT'] = os.environ.get('SECURITY_PASSWORD_SALT', 'salt_sicurezza_link')

database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- CONFIGURAZIONE EMAIL (PORTA 587 STANDARD + FIX IPV4) ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')

# Pulizia spazi vuoti nelle variabili
if app.config['MAIL_USERNAME']: app.config['MAIL_USERNAME'] = app.config['MAIL_USERNAME'].strip()
if app.config['MAIL_PASSWORD']: app.config['MAIL_PASSWORD'] = app.config['MAIL_PASSWORD'].strip()

db = SQLAlchemy(app)
mail = Mail(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    color = db.Column(db.String(20), default='#ffffff')
    confirmed = db.Column(db.Boolean, default=False)
    is_streamer = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    try:
        db.create_all()
        log("✅ Database inizializzato.")
    except Exception as e:
        log(f"❌ Errore Database: {e}")

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

def send_confirmation_email(user_email):
    token = serializer.dumps(user_email, salt=app.config['SECURITY_PASSWORD_SALT'])
    confirm_url = url_for('confirm_email', token=token, _external=True)
    
    log(f"\n🔗 LINK ATTIVAZIONE (Backup): {confirm_url}\n")

    if app.config['MAIL_USERNAME'] and app.config['MAIL_PASSWORD']:
        try:
            sender_info = ('PyStream Support', app.config['MAIL_USERNAME'])
            msg = Message('Conferma Account PyStream', 
                          sender=sender_info, 
                          recipients=[user_email])
            msg.body = f'Clicca per attivare: {confirm_url}'
            msg.html = f'''
            <div style="font-family: sans-serif; padding: 20px;">
                <h2 style="color: #2563eb;">Benvenuto!</h2>
                <p>Clicca qui sotto per confermare la tua email:</p>
                <a href="{confirm_url}" style="background-color: #2563eb; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">Conferma Email</a>
            </div>
            '''
            mail.send(msg)
            log(f"✅ MAIL INVIATA A {user_email} (IPv4 Forzato)")
        except Exception as e:
            log(f"❌ ERRORE INVIO MAIL: {e}")
    else:
        log("⚠️ Mail non configurata su Render.")

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

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
            camera = cv2.VideoCapture(0)
            if not camera.isOpened():
                flash("Nessuna webcam trovata.", "error")
                return redirect(url_for('index'))
            streaming_active = True
            socketio.emit('stream_status', {'status': 'live'})
        except: flash("Errore webcam", "error")
    else:
        streaming_active = False
        if camera: camera.release(); camera = None
        socketio.emit('stream_status', {'status': 'offline'})
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'register':
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            
            if User.query.filter_by(email=email).first():
                flash('Email già usata', 'error'); return redirect(url_for('login'))
            if User.query.filter_by(username=username).first():
                flash('Username già preso', 'error'); return redirect(url_for('login'))

            try:
                new_user = User(username=username, email=email, password=generate_password_hash(password, method='pbkdf2:sha256'), color=random.choice(['#ef4444', '#3b82f6', '#10b981']), confirmed=False)
                db.session.add(new_user)
                db.session.commit()
                send_confirmation_email(email)
                flash('Registrazione ok! Controlla la mail.', 'info')
                return redirect(url_for('login'))
            except Exception as e:
                db.session.rollback()
                log(f"❌ Errore critico DB: {e}")
                flash('Errore server.', 'error')

        elif action == 'login':
            user = User.query.filter_by(username=request.form.get('username')).first()
            if user and check_password_hash(user.password, request.form.get('password')):
                if not user.confirmed: flash('Account non attivo! Conferma la mail.', 'warning')
                else: login_user(user); return redirect(url_for('index'))
            else: flash('Dati errati', 'error')
    return render_template('login.html')

@app.route('/confirm/<token>')
def confirm_email(token):
    try: email = serializer.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=3600)
    except: flash('Link scaduto.', 'error'); return redirect(url_for('login'))
    user = User.query.filter_by(email=email).first_or_404()
    if not user.confirmed:
        user.confirmed = True
        db.session.add(user)
        db.session.commit()
        flash('Email confermata! Accedi.', 'success')
    return redirect(url_for('login'))A

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

@socketio.on('send_message')
def handle_message(data):
    if current_user.is_authenticated: emit('new_message', {'username': current_user.username, 'message': data['message'], 'color': current_user.color}, broadcast=True)

@socketio.on('send_tip')
def handle_tip(data):
    if current_user.is_authenticated: emit('new_tip', {'username': current_user.username, 'amount': data['amount']}, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
