from flask import Flask, render_template, request, redirect, url_for, session, g, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import os
from datetime import datetime
import requests
import threading
import time

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, 'data.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'change_this_secret_in_production'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

# Notification functions
def create_notification(user_id, notification_type, title, message, related_id=None, related_type=None):
    """Create a new notification for a user"""
    execute_db('''INSERT INTO notifications
                  (user_id, type, title, message, related_id, related_type, created_at)
                  VALUES (?, ?, ?, ?, ?, ?, ?)''',
               [user_id, notification_type, title, message, related_id, related_type,
                datetime.utcnow().isoformat()])

def get_user_notifications(user_id, limit=50):
    """Get notifications for a user, ordered by creation date (newest first)"""
    return query_db('''SELECT n.*, u.username as related_username
                      FROM notifications n
                      LEFT JOIN users u ON n.related_id = u.id AND n.related_type = 'user'
                      WHERE n.user_id = ?
                      ORDER BY n.created_at DESC
                      LIMIT ?''', [user_id, limit])

def get_unread_count(user_id):
    """Get count of unread notifications for a user"""
    result = query_db('SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0',
                      [user_id], one=True)
    return result['count'] if result else 0

def mark_notification_read(notification_id, user_id):
    """Mark a specific notification as read"""
    execute_db('UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?',
               [notification_id, user_id])

def mark_all_notifications_read(user_id):
    """Mark all notifications as read for a user"""
    execute_db('UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0', [user_id])

def delete_notification(notification_id, user_id):
    """Delete a specific notification"""
    execute_db('DELETE FROM notifications WHERE id = ? AND user_id = ?', [notification_id, user_id])

@app.context_processor
def inject_notification_count():
    """Make notification count available to all templates"""
    if session.get('user_id'):
        unread_notifications = get_unread_count(session['user_id'])
        unread_messages = query_db('SELECT COUNT(*) as count FROM messages WHERE receiver_id = ? AND is_read = 0',
                                   [session['user_id']], one=True)
        unread_messages_count = unread_messages['count'] if unread_messages else 0
        return {
            'notification_count': unread_notifications,
            'unread_count': unread_messages_count
        }
    return {'notification_count': 0, 'unread_count': 0}

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
        pitches = query_db('SELECT p.id, p.title, p.summary, p.content, p.category, p.image, p.created_at, u.username FROM pitches p JOIN users u ON p.author_id = u.id WHERE p.title LIKE ? OR p.content LIKE ? ORDER BY p.created_at DESC', ['%' + search_query + '%', '%' + search_query + '%'])
    else:
        pitches = query_db('SELECT p.id, p.title, p.summary, p.content, p.category, p.image, p.created_at, u.username FROM pitches p JOIN users u ON p.author_id = u.id ORDER BY p.created_at DESC')
    return render_template('index.html', pitches=pitches, search_query=search_query)

@app.route('/pitch/<int:pitch_id>')
def pitch(pitch_id):
    p = query_db('SELECT p.*, u.username, u.id as author_user_id FROM pitches p JOIN users u ON p.author_id = u.id WHERE p.id = ?', [pitch_id], one=True)
    if p is None:
        return "Pitch not found", 404
    
    # Get like count and check if current user liked
    like_count = query_db('SELECT COUNT(*) as count FROM likes WHERE pitch_id = ?', [pitch_id], one=True)['count']
    user_liked = False
    if session.get('user_id'):
        user_liked = query_db('SELECT * FROM likes WHERE pitch_id = ? AND user_id = ?', 
                             [pitch_id, session['user_id']], one=True) is not None
    
    # Get comments with usernames
    comments = query_db('''SELECT c.*, u.username 
                          FROM comments c 
                          JOIN users u ON c.user_id = u.id 
                          WHERE c.pitch_id = ? 
                          ORDER BY c.created_at DESC''', [pitch_id])
    
    return render_template('pitch.html', p=p, like_count=like_count, user_liked=user_liked, comments=comments)

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
        # Get basic fields
        title = request.form.get('title', '').strip()
        summary = request.form.get('summary', '').strip()
        content = request.form.get('content', '').strip()
        category = request.form.get('category', '').strip()
        tags = request.form.get('tags', '').strip()
        
        # Get additional fields
        funding_goal = request.form.get('funding_goal', '').strip()
        stage = request.form.get('stage', '').strip()
        team_size = request.form.get('team_size', '').strip()
        location = request.form.get('location', '').strip()
        website = request.form.get('website', '').strip()
        demo_url = request.form.get('demo_url', '').strip()
        
        # Get checkboxes (looking_for)
        looking_for = request.form.getlist('looking_for')
        looking_for_str = ','.join(looking_for) if looking_for else ''
        
        # Validate required fields
        if not title or not content or not summary or not category:
            flash('Title, category, elevator pitch, and detailed description are required', 'error')
            return redirect(url_for('post'))
        
        # Handle image upload
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Add timestamp to filename to make it unique
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                image_filename = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        
        # Insert into database with all fields
        execute_db('''INSERT INTO pitches 
                     (title, summary, content, category, tags, image, funding_goal, stage, 
                      team_size, location, website, demo_url, looking_for, author_id, created_at) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                   [title, summary, content, category, tags, image_filename, funding_goal, stage,
                    team_size, location, website, demo_url, looking_for_str, session['user_id'], 
                    datetime.utcnow().isoformat()])
        
        flash('Pitch posted successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('post.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = query_db('SELECT * FROM users WHERE id = ?', [session['user_id']], one=True)
    pitches = query_db('SELECT * FROM pitches WHERE author_id = ? ORDER BY created_at DESC', [session['user_id']])

    # Get unread message count
    unread_count = query_db('SELECT COUNT(*) as count FROM messages WHERE receiver_id = ? AND is_read = 0', 
                           [session['user_id']], one=True)['count']

    # Get unread notification count
    notification_count = get_unread_count(session['user_id'])

    return render_template('dashboard.html', user=user, pitches=pitches, unread_count=unread_count, notification_count=notification_count)

# Like/Unlike pitch
@app.route('/pitch/<int:pitch_id>/like', methods=['POST'])
@login_required
def like_pitch(pitch_id):
    user_id = session['user_id']
    existing = query_db('SELECT * FROM likes WHERE pitch_id = ? AND user_id = ?', [pitch_id, user_id], one=True)

    # Get pitch info to find the author
    pitch = query_db('SELECT * FROM pitches WHERE id = ?', [pitch_id], one=True)
    if not pitch:
        return {'success': False, 'error': 'Pitch not found'}, 404

    if existing:
        # Unlike
        execute_db('DELETE FROM likes WHERE pitch_id = ? AND user_id = ?', [pitch_id, user_id])
        liked = False
    else:
        # Like
        execute_db('INSERT INTO likes (pitch_id, user_id, created_at) VALUES (?, ?, ?)',
                  [pitch_id, user_id, datetime.utcnow().isoformat()])
        liked = True

        # Create notification for pitch author (if not liking own pitch)
        if pitch['author_id'] != user_id:
            liker = query_db('SELECT username FROM users WHERE id = ?', [user_id], one=True)
            if liker:
                create_notification(
                    user_id=pitch['author_id'],
                    notification_type='like',
                    title='New Like on Your Pitch',
                    message=f"{liker['username']} liked your pitch '{pitch['title']}'",
                    related_id=pitch_id,
                    related_type='pitch'
                )

    # Get updated like count
    like_count = query_db('SELECT COUNT(*) as count FROM likes WHERE pitch_id = ?', [pitch_id], one=True)['count']

    return {'success': True, 'liked': liked, 'like_count': like_count}

# Add comment
@app.route('/pitch/<int:pitch_id>/comment', methods=['POST'])
@login_required
def add_comment(pitch_id):
    content = request.form.get('content', '').strip()
    if not content:
        return {'success': False, 'error': 'Comment cannot be empty'}, 400

    # Get pitch info to find the author
    pitch = query_db('SELECT * FROM pitches WHERE id = ?', [pitch_id], one=True)
    if not pitch:
        return {'success': False, 'error': 'Pitch not found'}, 404

    execute_db('INSERT INTO comments (pitch_id, user_id, content, created_at) VALUES (?, ?, ?, ?)',
              [pitch_id, session['user_id'], content, datetime.utcnow().isoformat()])

    # Create notification for pitch author (if not commenting on own pitch)
    if pitch['author_id'] != session['user_id']:
        commenter = query_db('SELECT username FROM users WHERE id = ?', [session['user_id']], one=True)
        if commenter:
            create_notification(
                user_id=pitch['author_id'],
                notification_type='comment',
                title='New Comment on Your Pitch',
                message=f"{commenter['username']} commented on your pitch '{pitch['title']}'",
                related_id=pitch_id,
                related_type='pitch'
            )

    flash('Comment added successfully!', 'success')
    return redirect(url_for('pitch', pitch_id=pitch_id))

# Delete comment
@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = query_db('SELECT * FROM comments WHERE id = ?', [comment_id], one=True)
    if comment and comment['user_id'] == session['user_id']:
        execute_db('DELETE FROM comments WHERE id = ?', [comment_id])
        flash('Comment deleted', 'success')
    return redirect(request.referrer or url_for('index'))

# Messages inbox
@app.route('/messages')
@login_required
def messages():
    # Get received messages
    received = query_db('''SELECT m.*, u.username as sender_name 
                          FROM messages m 
                          JOIN users u ON m.sender_id = u.id 
                          WHERE m.receiver_id = ? 
                          ORDER BY m.created_at DESC''', [session['user_id']])
    
    # Get sent messages
    sent = query_db('''SELECT m.*, u.username as receiver_name 
                      FROM messages m 
                      JOIN users u ON m.receiver_id = u.id 
                      WHERE m.sender_id = ? 
                      ORDER BY m.created_at DESC''', [session['user_id']])
    
    return render_template('messages.html', received=received, sent=sent)

# Send message
@app.route('/message/send/<int:user_id>', methods=['GET', 'POST'])
@login_required
def send_message(user_id):
    receiver = query_db('SELECT * FROM users WHERE id = ?', [user_id], one=True)
    if not receiver:
        flash('User not found', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        content = request.form.get('content', '').strip()
        
        if not content:
            flash('Message content is required', 'error')
            return redirect(url_for('send_message', user_id=user_id))
        
        execute_db('''INSERT INTO messages (sender_id, receiver_id, subject, content, created_at) 
                     VALUES (?, ?, ?, ?, ?)''',
                  [session['user_id'], user_id, subject, content, datetime.utcnow().isoformat()])
        
        # Create notification for message receiver
        sender = query_db('SELECT username FROM users WHERE id = ?', [session['user_id']], one=True)
        if sender:
            create_notification(
                user_id=user_id,
                notification_type='message',
                title='New Message',
                message=f"You have a new message from {sender['username']}",
                related_id=session['user_id'],
                related_type='user'
            )

        flash('Message sent successfully!', 'success')
        return redirect(url_for('messages'))
    
    return render_template('send_message.html', receiver=receiver)

# Mark message as read
@app.route('/message/<int:message_id>/read', methods=['POST'])
@login_required
def mark_read(message_id):
    message = query_db('SELECT * FROM messages WHERE id = ?', [message_id], one=True)
    if message and message['receiver_id'] == session['user_id']:
        execute_db('UPDATE messages SET is_read = 1 WHERE id = ?', [message_id])
    return {'success': True}

# Notifications
@app.route('/notifications')
@login_required
def notifications():
    """View all notifications for the current user"""
    user_notifications = get_user_notifications(session['user_id'])
    return render_template('notifications.html', notifications=user_notifications)

@app.route('/notifications/mark_read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read_route(notification_id):
    """Mark a specific notification as read"""
    mark_notification_read(notification_id, session['user_id'])
    return redirect(url_for('notifications'))

@app.route('/notifications/mark_all_read', methods=['POST'])
@login_required
def mark_all_notifications_read_route():
    """Mark all notifications as read"""
    mark_all_notifications_read(session['user_id'])
    return redirect(url_for('notifications'))

@app.route('/notifications/delete/<int:notification_id>', methods=['POST'])
@login_required
def delete_notification_route(notification_id):
    """Delete a specific notification"""
    delete_notification(notification_id, session['user_id'])
    return redirect(url_for('notifications'))

@app.route('/admin', methods=['GET','POST'])
@role_required(['admin'])
def admin():
    if request.method == 'POST':
        action = request.form.get('action')
        target = request.form.get('target')
        pitch_id = request.form.get('pitch_id')
        
        if action == 'promote' and target:
            execute_db('UPDATE users SET role = ? WHERE username = ?', [request.form.get('newrole','verified'), target])
            flash('User role updated successfully!', 'success')
        elif action == 'delete_user' and target:
            execute_db('DELETE FROM users WHERE username = ?', [target])
            flash('User deleted successfully!', 'success')
        elif action == 'delete_pitch' and pitch_id:
            execute_db('DELETE FROM pitches WHERE id = ?', [pitch_id])
            flash('Pitch deleted successfully!', 'success')
        
        return redirect(url_for('admin'))
    
    # Get all users with pitch counts
    users = query_db('''SELECT u.id, u.username, u.role, u.created_at,
                       (SELECT COUNT(*) FROM pitches WHERE author_id = u.id) as pitch_count
                       FROM users u ORDER BY u.created_at DESC''')
    
    # Get all pitches with author info
    pitches = query_db('''SELECT p.*, u.username 
                         FROM pitches p 
                         JOIN users u ON p.author_id = u.id 
                         ORDER BY p.created_at DESC''')
    
    # Get statistics
    total_users = len(users)
    total_pitches = len(pitches)
    total_comments = query_db('SELECT COUNT(*) as count FROM comments', one=True)['count']
    total_likes = query_db('SELECT COUNT(*) as count FROM likes', one=True)['count']
    
    return render_template('admin.html', 
                          users=users, 
                          pitches=pitches,
                          total_users=total_users,
                          total_pitches=total_pitches,
                          total_comments=total_comments,
                          total_likes=total_likes)
def ping_self():
    while True:
        try:
            requests.get("https://ideabridge.onrender.com")  # Replace with your app URL
            print("Self ping successful")
        except Exception as e:
            print(f"Ping failed: {e}")
        time.sleep(600)  # Ping every 10 minutes

if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        from init_db import init_db
        init_db(DB_PATH)
    # Add notifications table if it doesn't exist (for existing databases)
    try:
        from add_notifications import add_notifications_table
        add_notifications_table(DB_PATH)
    except Exception as e:
        print(f"Note: Could not add notifications table: {e}")
    threading.Thread(target=ping_self, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
