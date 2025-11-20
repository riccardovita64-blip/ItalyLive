import os
import random
import sys
# Nota: Nessun import di socket o fix ipv4 qui, causano crash con Gunicorn!

from flask import Flask, render_template, request, redirect, url_for, flash, Response, jsonify
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
import cv2
import resend
import stripe

# Funzione helper per i log di Render
def log(message):
    print(message, file=sys.stdout, flush=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chiave_segreta_default_per_sviluppo')
app.config['SECURITY_PASSWORD_SALT'] = os.environ.get('SECURITY_PASSWORD_SALT', 'salt_sicurezza_link')

# --- STRIPE ---
stripe_key = os.environ.get('STRIPE_SECRET_KEY')
if stripe_key:
    stripe.api_key = stripe_key.strip() # Rimuove spazi pericolosi
else:
    log("⚠️ ATTENZIONE: STRIPE_SECRET_KEY mancante su Render!")

# Pulisce l'URL del dominio (toglie slash finale se c'è)
DOMAIN = os.environ.get('DOMAIN_URL', 'http://127.0.0.1:5000').strip('/')

# --- DATABASE ---
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- RESEND ---
resend_key = os.environ.get('RESEND_API_KEY')
if resend_key:
    resend.api_key = resend_key.strip()

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")
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
    color = db.Column(db.String(20), default='#ffffff')
    confirmed = db.Column(db.Boolean, default=False)
    is_streamer = db.Column(db.Boolean, default=False)

class Stream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(300))
    is_live = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- INIT DB ---
def init_db():
    db.create_all()
    if Stream.query.count() == 0:
        s1 = Stream(title="Galleria degli Uffizi", description="Tour notturno esclusivo tra i capolavori del Rinascimento.", image_url="https://images.unsplash.com/photo-1580226326847-e7b5c2d5c043", is_live=True)
        s2 = Stream(title="Parco Archeologico di Pompei", description="Passeggiata tra le rovine della città eterna al tramonto.", image_url="https://images.unsplash.com/photo-1555661879-423a5383a674", is_live=False)
        s3 = Stream(title="Colosseo - Arena", description="Visita in prima persona nell'anfiteatro più famoso del mondo.", image_url="https://images.unsplash.com/photo-1552832230-c0197dd311b5", is_live=False)
        db.session.add_all([s1, s2, s3])
        db.session.commit()

with app.app_context():
    try:
        init_db()
        log("✅ Database pronto.")
    except Exception as e:
        log(f"❌ Errore Database: {e}")

# --- CAMERA ---
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

# --- MAIL (RESEND) ---
def send_confirmation_email(user_email):
    token = serializer.dumps(user_email, salt=app.config['SECURITY_PASSWORD_SALT'])
    confirm_url = url_for('confirm_email', token=token, _external=True)
    
    log(f"\n🔗 LINK ATTIVAZIONE (Backup Logs): {confirm_url}\n")

    if os.environ.get('RESEND_API_KEY'):
        try:
            params = {
                "from": "onboarding@resend.dev",
                "to": [user_email],
                "subject": "Benvenuto in ItalyFromCouch",
                "html": f'''
                <div style="font-family: sans-serif; padding: 20px; text-align: center;">
                    <h2 style="color: #d97706;">ItalyFromCouch</h2>
                    <p>Grazie per esserti registrato!</p>
                    <a href="{confirm_url}" style="background-color: #d97706; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 20px 0;">CONFERMA EMAIL</a>
                    <p style="font-size: 12px; color: #666;">Se il bottone non funziona: {confirm_url}</p>
                </div>
                '''
            }
            r = resend.Emails.send(params)
            log(f"✅ Mail inviata via Resend. ID: {r.get('id')}")
        except Exception as e:
            log(f"❌ Errore invio Resend: {e}")
    else:
        log("⚠️ RESEND_API_KEY mancante.")

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# --- ROTTE PAGAMENTI (STRIPE) ---
@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    try:
        data = request.json
        amount_eur = data.get('amount', 5)
        stream_id = data.get('stream_id', 1)
        
        # Verifica chiave Stripe
        if not stripe.api_key:
            return jsonify({'error': 'Server payment config error'}), 500

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': 'Supporto Museo',
                        'description': f'Donazione da {current_user.username}',
                        'images': ['https://images.unsplash.com/photo-1552832230-c0197dd311b5'],
                    },
                    'unit_amount': int(float(amount_eur) * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            metadata={
                'username': current_user.username,
                'amount': amount_eur,
                'stream_id': stream_id
            },
            success_url=DOMAIN + '/payment/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=DOMAIN + f'/watch/{stream_id}',
        )
        return jsonify({'url': checkout_session.url})
    except Exception as e:
        log(f"❌ Stripe Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/payment/success')
@login_required
def payment_success():
    session_id = request.args.get('session_id')
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            donor = session.metadata.get('username', 'Anonimo')
            amount = session.metadata.get('amount', '0')
            stream_id = session.metadata.get('stream_id', '1')
            
            socketio.emit('new_tip', {'username': donor, 'amount': amount})
            flash(f"Grazie {donor}! Donazione di {amount}€ ricevuta.", "success")
            return redirect(url_for('watch', stream_id=stream_id))
        except Exception as e:
            log(f"❌ Errore verifica pagamento: {e}")
            return redirect(url_for('index'))
    return redirect(url_for('index'))

@app.route('/payment/cancel')
def payment_cancel():
    flash("Pagamento annullato.", "info")
    return redirect(url_for('index'))

# --- ALTRE ROTTE ---
@app.route('/')
@login_required
def index():
    streams = Stream.query.all()
    return render_template('dashboard.html', username=current_user.username, streams=streams)

@app.route('/watch/<int:stream_id>')
@login_required
def watch(stream_id):
    stream = Stream.query.get_or_404(stream_id)
    return render_template('stream.html', username=current_user.username, stream=stream, is_live=streaming_active)

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
                flash("Nessuna camera trovata.", "error")
                return redirect(request.referrer)
            streaming_active = True
            socketio.emit('stream_status', {'status': 'live'})
        except: flash("Errore webcam", "error")
    else:
        streaming_active = False
        if camera: camera.release(); camera = None
        socketio.emit('stream_status', {'status': 'offline'})
    return redirect(request.referrer)

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
                new_user = User(username=username, email=email, password=generate_password_hash(password, method='pbkdf2:sha256'), confirmed=False)
                db.session.add(new_user)
                db.session.commit()
                send_confirmation_email(email)
                flash('Registrazione ok! Controlla la mail.', 'info')
                return redirect(url_for('login'))
            except: db.session.rollback(); flash('Errore server.', 'error')

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
    return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

@socketio.on('send_message')
def handle_message(data):
    if current_user.is_authenticated: emit('new_message', {'username': current_user.username, 'message': data['message'], 'color': current_user.color}, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
