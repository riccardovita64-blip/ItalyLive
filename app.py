import os
import random
import sys
from flask import Flask, render_template, request, redirect, url_for, flash, Response, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
import stripe
import resend

def log(message):
    print(message, file=sys.stdout, flush=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chiave_segreta_default')
app.config['SECURITY_PASSWORD_SALT'] = os.environ.get('SECURITY_PASSWORD_SALT', 'salt_link')

# --- CONFIGURAZIONE ESTRNI ---
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '').strip()
DOMAIN = os.environ.get('DOMAIN_URL', 'http://127.0.0.1:5000').strip('/')
resend.api_key = os.environ.get('RESEND_API_KEY', '').strip()

# --- DATABASE ---
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# --- MODELLI ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    confirmed = db.Column(db.Boolean, default=False)
    is_streamer = db.Column(db.Boolean, default=False) # Se True, può vedere il tasto "Trasmetti"

class Stream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(300))
    is_live = db.Column(db.Boolean, default=False)
    guide_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Chi sta trasmettendo?

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- INIT DB ---
with app.app_context():
    db.create_all()
    if Stream.query.count() == 0:
        s1 = Stream(title="Galleria degli Uffizi", description="Tour notturno esclusivo tra i capolavori.", image_url="https://images.unsplash.com/photo-1580226326847-e7b5c2d5c043")
        s2 = Stream(title="Parco Archeologico di Pompei", description="Passeggiata tra le rovine.", image_url="https://images.unsplash.com/photo-1555661879-423a5383a674")
        s3 = Stream(title="Colosseo - Arena", description="Visita nell'anfiteatro.", image_url="https://images.unsplash.com/photo-1552832230-c0197dd311b5")
        db.session.add_all([s1, s2, s3])
        db.session.commit()

# --- INVIO MAIL (Semplificato) ---
def send_confirmation_email(user_email):
    token = serializer.dumps(user_email, salt=app.config['SECURITY_PASSWORD_SALT'])
    confirm_url = url_for('confirm_email', token=token, _external=True)
    log(f"\n🔗 LINK ATTIVAZIONE: {confirm_url}\n")
    if os.environ.get('RESEND_API_KEY'):
        try:
            resend.Emails.send({
                "from": "onboarding@resend.dev",
                "to": [user_email],
                "subject": "Attiva Account ItalyFromCouch",
                "html": f'<a href="{confirm_url}">Conferma Email</a>'
            })
        except Exception as e: log(f"Errore Resend: {e}")

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# --- ROTTE ---
@app.route('/')
@login_required
def index():
    streams = Stream.query.all()
    return render_template('dashboard.html', user=current_user, streams=streams) # Passo l'intero oggetto user

@app.route('/watch/<int:stream_id>')
@login_required
def watch(stream_id):
    stream = Stream.query.get_or_404(stream_id)
    return render_template('stream.html', user=current_user, stream=stream)

# --- NUOVA ROTTA: STUDIO DI TRASMISSIONE (Solo per Guide) ---
@app.route('/broadcast/<int:stream_id>')
@login_required
def broadcast(stream_id):
    if not current_user.is_streamer:
        flash("Non sei abilitato a trasmettere.", "error")
        return redirect(url_for('index'))
    
    stream = Stream.query.get_or_404(stream_id)
    return render_template('broadcast.html', user=current_user, stream=stream)

# --- ROTTA SEGRETA: DIVENTA GUIDA ---
@app.route('/become_guide')
@login_required
def become_guide():
    current_user.is_streamer = True
    db.session.commit()
    flash("Ora sei una Guida Ufficiale! Puoi trasmettere.", "success")
    return redirect(url_for('index'))

# --- SOCKETS: VIDEO RELAY ---
@socketio.on('join_stream')
def on_join(data):
    room = data['stream_id']
    join_room(room)
    log(f"Utente {current_user.username} entrato nella stanza {room}")

@socketio.on('stream_frame')
def on_stream_frame(data):
    # La guida manda un frame -> Il server lo gira a tutti nella stanza
    room = data['stream_id']
    image_data = data['image'] # Base64 image
    emit('video_update', {'image': image_data}, room=room, include_self=False)

@socketio.on('stream_status_change')
def on_status_change(data):
    room = data['stream_id']
    is_live = data['status'] == 'live'
    
    # Aggiorna DB
    stream = Stream.query.get(room)
    if stream:
        stream.is_live = is_live
        db.session.commit()
    
    emit('status_update', {'is_live': is_live}, room=room)

# --- CHAT & TIP ---
@socketio.on('send_message')
def handle_message(data):
    room = data.get('stream_id')
    if room:
        emit('new_message', {'username': current_user.username, 'message': data['message']}, room=room)

@socketio.on('send_tip')
def handle_tip(data):
    room = data.get('stream_id')
    if room:
        emit('new_tip', {'username': current_user.username, 'amount': data['amount']}, room=room)

# --- LOGIN/LOGOUT ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'register':
            # ... (logica registrazione invariata) ...
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            if User.query.filter_by(email=email).first(): flash('Email usata', 'error'); return redirect(url_for('login'))
            new_user = User(username=username, email=email, password=generate_password_hash(password, method='pbkdf2:sha256'))
            db.session.add(new_user); db.session.commit()
            send_confirmation_email(email)
            flash('Registrato! Controlla la mail.', 'info'); return redirect(url_for('login'))
        elif action == 'login':
            user = User.query.filter_by(username=request.form.get('username')).first()
            if user and check_password_hash(user.password, request.form.get('password')):
                if not user.confirmed: flash('Conferma la mail!', 'warning')
                else: login_user(user); return redirect(url_for('index'))
            else: flash('Dati errati', 'error')
    return render_template('login.html')

@app.route('/confirm/<token>')
def confirm_email(token):
    try: email = serializer.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=3600)
    except: flash('Link scaduto.', 'error'); return redirect(url_for('login'))
    user = User.query.filter_by(email=email).first_or_404()
    user.confirmed = True; db.session.commit()
    flash('Email confermata!', 'success'); return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

# --- STRIPE ---
@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    # ... (Logica Stripe Invariata) ...
    # Assicurati di includere la logica Stripe dal messaggio precedente se vuoi i pagamenti
    return jsonify({'error': 'Stripe temporaneamente disabilitato per brevità'}), 500

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
