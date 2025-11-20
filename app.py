# --- CRITICAL FIX FOR STRIPE/GEVENT ---
from gevent import monkey
monkey.patch_all()
# --------------------------------------

import os
import random
import sys
from flask import Flask, render_template, request, redirect, url_for, flash, Response, jsonify
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
import stripe
import resend

def log(message):
    print(message, file=sys.stdout, flush=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret_key_default')
app.config['SECURITY_PASSWORD_SALT'] = os.environ.get('SECURITY_PASSWORD_SALT', 'salt_link')

# --- EXTERNAL CONFIG ---
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

# --- MODELS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    confirmed = db.Column(db.Boolean, default=False)
    is_streamer = db.Column(db.Boolean, default=False)
    rating = db.Column(db.Float, default=5.0) # Stelle della guida (max 5.0)
    reviews_count = db.Column(db.Integer, default=0)

class Stream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(300))
    is_live = db.Column(db.Boolean, default=False)
    # Colleghiamo lo stream a una guida specifica
    guide_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    guide = db.relationship('User', backref='streams')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- INIT DB (Popoliamo con Guide Reali) ---
def init_db():
    db.create_all()
    if Stream.query.count() == 0:
        # 1. Creiamo le Guide
        guide1 = User(username="Giulia_Archeo", email="giulia@test.com", password=generate_password_hash("pass", method='pbkdf2:sha256'), confirmed=True, is_streamer=True, rating=4.9, reviews_count=120)
        guide2 = User(username="Marco_Roma", email="marco@test.com", password=generate_password_hash("pass", method='pbkdf2:sha256'), confirmed=True, is_streamer=True, rating=4.7, reviews_count=85)
        guide3 = User(username="Sofia_Art", email="sofia@test.com", password=generate_password_hash("pass", method='pbkdf2:sha256'), confirmed=True, is_streamer=True, rating=5.0, reviews_count=42)
        
        db.session.add_all([guide1, guide2, guide3])
        db.session.commit()

        # 2. Creiamo gli Stream assegnati alle guide
        s1 = Stream(title="Uffizi Gallery Night Tour", description="Exclusive night tour among Renaissance masterpieces.", image_url="https://images.unsplash.com/photo-1580226326847-e7b5c2d5c043", is_live=True, guide_id=guide3.id)
        s2 = Stream(title="Pompeii Ruins at Sunset", description="Walking through the eternal city ruins.", image_url="https://images.unsplash.com/photo-1555661879-423a5383a674", is_live=False, guide_id=guide1.id)
        s3 = Stream(title="Colosseum Underground", description="Deep dive into the gladiator pits.", image_url="https://images.unsplash.com/photo-1552832230-c0197dd311b5", is_live=False, guide_id=guide2.id)
        
        db.session.add_all([s1, s2, s3])
        db.session.commit()
        log("✅ Database initialized with Guides and Streams.")

# --- EMAIL ---
def send_confirmation_email(user_email):
    token = serializer.dumps(user_email, salt=app.config['SECURITY_PASSWORD_SALT'])
    confirm_url = url_for('confirm_email', token=token, _external=True)
    
    log(f"\n🔗 ACTIVATION LINK (Backup): {confirm_url}\n")
    
    if os.environ.get('RESEND_API_KEY'):
        try:
            resend.Emails.send({
                "from": "onboarding@resend.dev",
                "to": [user_email],
                "subject": "Welcome to ItalyFromCouch",
                "html": f'''
                <div style="font-family: sans-serif; text-align: center;">
                    <h2>Welcome to ItalyFromCouch! 🇮🇹</h2>
                    <p>Click below to activate your account:</p>
                    <a href="{confirm_url}" style="background:#d97706; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">Confirm Email</a>
                </div>
                '''
            })
            log(f"✅ Email sent to {user_email} via Resend.")
        except Exception as e: 
            log(f"❌ Resend Error: {e}")
            # Nota per l'utente: Resend Free invia solo alla tua mail registrata
            if "403" in str(e):
                log("⚠️ RESEND LIMIT: On Free Tier you can only send emails to YOURSELF.")

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# --- ROUTES ---
@app.route('/')
@login_required
def index():
    streams = Stream.query.all()
    return render_template('dashboard.html', user=current_user, streams=streams)

@app.route('/watch/<int:stream_id>')
@login_required
def watch(stream_id):
    stream = Stream.query.get_or_404(stream_id)
    return render_template('stream.html', user=current_user, stream=stream)

@app.route('/broadcast/<int:stream_id>')
@login_required
def broadcast(stream_id):
    if not current_user.is_streamer:
        flash("You must enable Guide Mode to broadcast.", "error")
        return redirect(url_for('index'))
    stream = Stream.query.get_or_404(stream_id)
    
    # Assegna questo stream alla guida corrente se non lo è già
    stream.guide_id = current_user.id
    db.session.commit()
    
    return render_template('broadcast.html', user=current_user, stream=stream)

@app.route('/become_guide')
@login_required
def become_guide():
    current_user.is_streamer = True
    # Diamo un rating di default alla nuova guida
    if current_user.rating is None:
        current_user.rating = 5.0
        current_user.reviews_count = 0
    db.session.commit()
    flash("Guide Mode Activated! You can now broadcast.", "success")
    return redirect(url_for('index'))

# --- SOCKETS ---
@socketio.on('join_stream')
def on_join(data):
    room = str(data['stream_id'])
    join_room(room)

@socketio.on('stream_frame')
def on_stream_frame(data):
    room = str(data['stream_id'])
    image_data = data['image']
    emit('video_update', {'image': image_data}, room=room, include_self=False)

@socketio.on('stream_status_change')
def on_status_change(data):
    room = str(data['stream_id'])
    is_live = data['status'] == 'live'
    stream = Stream.query.get(int(room))
    if stream:
        stream.is_live = is_live
        db.session.commit()
    emit('status_update', {'is_live': is_live}, room=room)

@socketio.on('send_message')
def handle_message(data):
    room = str(data.get('stream_id'))
    emit('new_message', {'username': current_user.username, 'message': data['message']}, room=room)

@socketio.on('send_tip')
def handle_tip(data):
    room = str(data.get('stream_id'))
    emit('new_tip', {'username': current_user.username, 'amount': data['amount']}, room=room)

# --- AUTH ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'register':
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            if User.query.filter_by(email=email).first(): flash('Email already in use', 'error'); return redirect(url_for('login'))
            new_user = User(username=username, email=email, password=generate_password_hash(password, method='pbkdf2:sha256'))
            db.session.add(new_user); db.session.commit()
            
            # Tentativo invio mail resiliente
            try:
                send_confirmation_email(email)
                flash('Registered! Check your email.', 'info')
            except:
                flash('Registered! Email failed (Check logs).', 'warning')
                
            return redirect(url_for('login'))
        elif action == 'login':
            user = User.query.filter_by(username=request.form.get('username')).first()
            if user and check_password_hash(user.password, request.form.get('password')):
                if not user.confirmed: flash('Please confirm your email!', 'warning')
                else: login_user(user); return redirect(url_for('index'))
            else: flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/confirm/<token>')
def confirm_email(token):
    try: email = serializer.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=3600)
    except: flash('Invalid link.', 'error'); return redirect(url_for('login'))
    user = User.query.filter_by(email=email).first_or_404()
    user.confirmed = True; db.session.commit()
    flash('Email confirmed! Login now.', 'success'); return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

# --- STRIPE ---
@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    try:
        data = request.json
        amount_eur = data.get('amount', 5)
        stream_id = data.get('stream_id', 1)
        
        if not stripe.api_key: return jsonify({'error': 'Stripe not configured'}), 500
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {'name': 'Museum Tip'},
                    'unit_amount': int(float(amount_eur) * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            metadata={'username': current_user.username, 'amount': amount_eur, 'stream_id': stream_id},
            success_url=DOMAIN + '/payment/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=DOMAIN + f'/watch/{stream_id}',
        )
        return jsonify({'url': checkout_session.url})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/payment/success')
@login_required
def payment_success():
    session_id = request.args.get('session_id')
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            donor = session.metadata.get('username', 'Anonymous')
            amount = session.metadata.get('amount', '0')
            stream_id = session.metadata.get('stream_id', '1')
            socketio.emit('new_tip', {'username': donor, 'amount': amount}, room=stream_id)
            flash(f"Thanks {donor}!", "success")
            return redirect(url_for('watch', stream_id=stream_id))
        except: pass
    return redirect(url_for('index'))

# Init Context
with app.app_context():
    try:
        init_db()
        log("✅ App initialized.")
    except Exception as e: log(f"❌ Init Error: {e}")

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
