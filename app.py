import os
import random
import sys # Aggiunto per forzare la stampa dei log
from flask import Flask, render_template, request, redirect, url_for, flash, Response
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
import cv2

# Funzione per forzare la stampa immediata nei log di Render
def log(message):
    print(message, file=sys.stdout, flush=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chiave_segreta_default_per_sviluppo')
app.config['SECURITY_PASSWORD_SALT'] = os.environ.get('SECURITY_PASSWORD_SALT', 'salt_sicurezza_link')

# --- CONFIGURAZIONE DATABASE ---
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- CONFIGURAZIONE EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEBUG'] = True 

db = SQLAlchemy(app)
mail = Mail(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# --- MODELLO UTENTE ---
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

# --- FIX DATABASE ---
with app.app_context():
    try:
        db.create_all()
        log("✅ Database inizializzato correttamente.")
    except Exception as e:
        log(f"❌ Errore Database all'avvio: {e}")

# --- GESTIONE CAMERA ---
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

# --- INVIO MAIL (CON DEBUG) ---
def send_confirmation_email(user_email):
    log(f"📧 Preparazione invio mail a: {user_email}")
    
    token = serializer.dumps(user_email, salt=app.config['SECURITY_PASSWORD_SALT'])
    confirm_url = url_for('confirm_email', token=token, _external=True)
    
    log(f"🔗 LINK DEBUG: {confirm_url}")

    if app.config['MAIL_USERNAME']:
        try:
            log(f"...Connessione a Gmail come {app.config['MAIL_USERNAME']}...")
            msg = Message('Conferma Account PyStream', 
                          sender=app.config['MAIL_USERNAME'], 
                          recipients=[user_email])
            msg.body = f'Clicca qui per attivare il tuo account: {confirm_url}'
            mail.send(msg)
            log("✅ MAIL INVIATA AL SERVER SMTP.")
        except Exception as e:
            log(f"❌ ERRORE INVIO MAIL: {e}")
            # Non facciamo 'raise' qui per permettere al sito di continuare
    else:
        log("⚠️ Variabile MAIL_USERNAME non trovata. Invio saltato.")

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
    # ... (codice streaming invariato) ...
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    
    if request.method == 'POST':
        # LOG DI DEBUG: Vediamo se la richiesta arriva
        log(f"📥 RICEVUTA RICHIESTA POST SU /LOGIN. Dati: {request.form.get('action')} - {request.form.get('username')}")
        
        action = request.form.get('action')
        username = request.form.get('username')
        password = request.form.get('password')

        if action == 'register':
            email = request.form.get('email')
            log("...Inizio procedura registrazione...")

            if User.query.filter_by(email=email).first():
                flash('Email già usata', 'error')
                log("...Errore: Email duplicata.")
                return redirect(url_for('login'))
            
            if User.query.filter_by(username=username).first():
                flash('Username già preso', 'error')
                log("...Errore: Username duplicato.")
                return redirect(url_for('login'))

            try:
                new_user = User(
                    username=username,
                    email=email,
                    password=generate_password_hash(password, method='pbkdf2:sha256'),
                    color=random.choice(['#ef4444', '#3b82f6', '#10b981']),
                    confirmed=False
                )
                db.session.add(new_user)
                
                log("...Utente aggiunto alla sessione DB, invio mail...")
                send_confirmation_email(email)
                
                log("...Mail gestita, eseguo commit DB...")
                db.session.commit()
                log("✅ Registrazione completata con successo!")
                
                flash('Registrazione ok! Controlla la mail.', 'info')
                return redirect(url_for('login'))
                
            except Exception as e:
                db.session.rollback()
                log(f"❌ ERRORE CRITICO DURANTE REGISTRAZIONE: {e}")
                flash('Errore server. Riprova.', 'error')

        elif action == 'login':
            # ... (logica login invariata) ...
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
                if not user.confirmed:
                    flash('Account non attivo! Conferma la mail.', 'warning')
                else:
                    login_user(user)
                    return redirect(url_for('index'))
            else:
                flash('Dati errati', 'error')

    return render_template('login.html')

@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = serializer.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=3600)
    except:
        flash('Link scaduto o non valido.', 'error')
        return redirect(url_for('login'))
    
    user = User.query.filter_by(email=email).first_or_404()
    if not user.confirmed:
        user.confirmed = True
        db.session.add(user)
        db.session.commit()
        flash('Email confermata! Accedi.', 'success')
    return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@socketio.on('send_message')
def handle_message(data):
    if current_user.is_authenticated:
        emit('new_message', {'username': current_user.username, 'message': data['message'], 'color': current_user.color}, broadcast=True)

@socketio.on('send_tip')
def handle_tip(data):
    if current_user.is_authenticated:
        emit('new_tip', {'username': current_user.username, 'amount': data['amount']}, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
