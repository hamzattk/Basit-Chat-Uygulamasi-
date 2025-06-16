
from gevent import monkey; monkey.patch_all()
from flask import Flask, render_template, request, json, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from datetime import datetime, timedelta
from functools import wraps
import os
from dotenv import load_dotenv
from gevent.pywsgi import WSGIServer

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/chat_app'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your-email@gmail.com'
app.config['MAIL_PASSWORD'] = 'your-app-specific-password'


db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
mail = Mail(app)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    email_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    messages = db.relationship('Message', backref='author', lazy=True)

class Room(db.Model):
    __tablename__ = 'rooms'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_private = db.Column(db.Boolean, default=False)
    messages = db.relationship('Message', backref='room', lazy=True)
    members = db.relationship('User', secondary='room_members', backref=db.backref('rooms', lazy='dynamic'))

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)

room_members = db.Table('room_members',
    db.Column('room_id', db.Integer, db.ForeignKey('rooms.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('joined_at', db.DateTime, default=datetime.utcnow)
)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def send_verification_email(user):
    token = jwt.encode(
        {'user_id': user.id, 'exp': datetime.utcnow() + timedelta(hours=24)},
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )
    msg = Message(
        subject='Email Doğrulama',
        sender=app.config['MAIL_USERNAME'],
        recipients=[user.email]
    )
    msg.body = f'''Email adresinizi doğrulamak için aşağıdaki linke tıklayın:
{url_for('verify_email', token=token, _external=True)}

Bu link 24 saat geçerlidir.
'''
    mail.send(msg)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Bu kullanıcı adı zaten kullanılıyor.', 'danger')
            return redirect(url_for('register'))
            
        if User.query.filter_by(email=email).first():
            flash('Bu email adresi zaten kayıtlı.', 'danger')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password)
        user = User(username=username, email=email, password=hashed_password, email_verified=True)
        db.session.add(user)
        db.session.commit()
        
        flash('Kayıt başarılı! Giriş yapabilirsiniz.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/verify-email/<token>')
def verify_email(token):
    try:
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        user = User.query.get(data['user_id'])
        if user:
            user.email_verified = True
            user.verification_token = None
            db.session.commit()
            flash('Email adresiniz başarıyla doğrulandı!', 'success')
        else:
            flash('Geçersiz doğrulama linki.', 'danger')
    except:
        flash('Geçersiz veya süresi dolmuş doğrulama linki.', 'danger')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main'))
        
        flash('Geçersiz kullanıcı adı veya şifre.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
def choose_name():
    if current_user.is_authenticated:
        return redirect(url_for('main'))
    return redirect(url_for('login'))

@app.route('/main')
@login_required
def main():
    rooms = Room.query.all()
    return render_template('main.html',
        uid=current_user.username,
        rooms=rooms
    )

@app.route('/create_room', methods=['POST'])
@login_required
def create_room():
    room_name = request.form.get('room_name')
    if not room_name:
        flash('Oda adı boş olamaz.', 'danger')
        return redirect(url_for('main'))
    
    if Room.query.filter_by(name=room_name).first():
        flash('Bu isimde bir oda zaten var.', 'danger')
        return redirect(url_for('main'))
    
    room = Room(name=room_name, created_by=current_user.id)
    room.members.append(current_user)  # Oda oluşturan kişiyi otomatik olarak üye yap
    db.session.add(room)
    db.session.commit()
    
    flash('Oda başarıyla oluşturuldu!', 'success')
    return redirect(url_for('main'))

@app.route('/room/<int:room_id>')
@login_required
def join_room(room_id):
    room = Room.query.get_or_404(room_id)
    messages = Message.query.filter_by(room_id=room_id).order_by(Message.created_at).all()
    
    return render_template('room.html',
        room=room,
        messages=messages,
        current_user=current_user,
        uid=current_user.username
    )

@app.route('/send_message/<int:room_id>', methods=['POST'])
@login_required
def send_message(room_id):
    message_content = request.form.get('message')
    if message_content:
        message = Message(
            content=message_content,
            user_id=current_user.id,
            room_id=room_id,
            created_at=datetime.utcnow()
        )
        db.session.add(message)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': {
                'id': message.id,
                'sender': current_user.username,
                'content': message_content,
                'time': message.created_at.strftime('%H:%M')
            }
        })
    return jsonify({'status': 'error', 'message': 'Boş mesaj gönderilemez'})

@app.route('/poll', methods=['POST'])
@login_required
def poll():
    try:
        room_id = request.form.get('room_id')
        last_message_id = request.form.get('last_message_id', 0, type=int)
        
        if room_id:
            message = Message.query.filter(
                Message.room_id == room_id,
                Message.id > last_message_id
            ).order_by(Message.id.asc()).first()
            
            if message:
                return jsonify({
                    'id': message.id,
                    'sender': message.author.username,
                    'content': message.content,
                    'time': message.created_at.strftime('%H:%M')
                })
    except Exception as e:
        app.logger.error(f"Polling error: {str(e)}")
    return jsonify(None)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Bu sayfaya erişim yetkiniz yok.', 'danger')
            return redirect(url_for('main'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    users = User.query.all()
    rooms = Room.query.all()
    return render_template('admin.html', users=users, rooms=rooms)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    print("Serving on http://0.0.0.0:5001")
    http = WSGIServer(('', 5001), app)
    http.serve_forever()

