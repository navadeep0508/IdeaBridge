from flask import Flask, render_template, request, redirect, url_for, session, g, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
from datetime import datetime

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, 'data.db')

app = Flask(__name__)
app.secret_key = 'change_this_secret_in_production'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    conn = get_db()
    cur = conn.execute(query, args)
    conn.commit()
    cur.close()
    return cur.lastrowid

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapped

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user = query_db('SELECT * FROM users WHERE id = ?', [session['user_id']], one=True)
            if user is None or user['role'] not in roles:
                flash('Insufficient permissions.', 'error')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return wrapped
    return decorator

@app.route('/')
def index():
    search_query = request.args.get('q', '').strip()
    if search_query:
        pitches = query_db('SELECT p.id, p.title, p.summary, p.content, p.created_at, u.username FROM pitches p JOIN users u ON p.author_id = u.id WHERE p.title LIKE ? OR p.content LIKE ? ORDER BY p.created_at DESC', ['%' + search_query + '%', '%' + search_query + '%'])
    else:
        pitches = query_db('SELECT p.id, p.title, p.summary, p.content, p.created_at, u.username FROM pitches p JOIN users u ON p.author_id = u.id ORDER BY p.created_at DESC')
    return render_template('index.html', pitches=pitches, search_query=search_query)

@app.route('/pitch/<int:pitch_id>')
def pitch(pitch_id):
    p = query_db('SELECT p.*, u.username FROM pitches p JOIN users u ON p.author_id = u.id WHERE p.id = ?', [pitch_id], one=True)
    if p is None:
        return "Pitch not found", 404
    return render_template('pitch.html', p=p)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        role = 'user'
        if not username or not password:
            flash('Provide username and password', 'error')
            return redirect(url_for('register'))
        existing = query_db('SELECT * FROM users WHERE username = ?', [username], one=True)
        if existing:
            flash('Username exists', 'error')
            return redirect(url_for('register'))
        pwd_hash = generate_password_hash(password)
        execute_db('INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)', [username, pwd_hash, role, datetime.utcnow().isoformat()])
        flash('Registered. Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user = query_db('SELECT * FROM users WHERE username = ?', [username], one=True)
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash('Logged in', 'success')
            return redirect(url_for('index'))
        flash('Invalid credentials', 'error')
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out', 'success')
    return redirect(url_for('index'))

@app.route('/post', methods=['GET','POST'])
@role_required(['admin', 'verified', 'experienced', 'user'])
def post():
    if request.method == 'POST':
        title = request.form['title'].strip()
        summary = request.form['summary'].strip()
        content = request.form['content'].strip()
        if not title or not content:
            flash('Title and content required', 'error')
            return redirect(url_for('post'))
        execute_db('INSERT INTO pitches (title, summary, content, author_id, created_at) VALUES (?, ?, ?, ?, ?)', [title, summary, content, session['user_id'], datetime.utcnow().isoformat()])
        flash('Pitch posted', 'success')
        return redirect(url_for('index'))
    return render_template('post.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = query_db('SELECT * FROM users WHERE id = ?', [session['user_id']], one=True)
    pitches = query_db('SELECT * FROM pitches WHERE author_id = ? ORDER BY created_at DESC', [session['user_id']])
    return render_template('dashboard.html', user=user, pitches=pitches)

@app.route('/admin', methods=['GET','POST'])
@role_required(['admin'])
def admin():
    if request.method == 'POST':
        action = request.form.get('action')
        target = request.form.get('target')
        if action == 'promote' and target:
            execute_db('UPDATE users SET role = ? WHERE username = ?', [request.form.get('newrole','verified'), target])
            flash('User updated', 'success')
        elif action == 'delete' and target:
            execute_db('DELETE FROM users WHERE username = ?', [target])
            flash('User deleted', 'success')
    users = query_db('SELECT id, username, role, created_at FROM users ORDER BY created_at DESC')
    return render_template('admin.html', users=users)

if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        from init_db import init_db
        init_db(DB_PATH)
    app.run(debug=True, host='0.0.0.0', port=5000)
