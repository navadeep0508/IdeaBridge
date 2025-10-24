import sqlite3, os
from werkzeug.security import generate_password_hash
from datetime import datetime

def init_db(db_path='data.db'):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT "user", created_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS pitches (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, summary TEXT, content TEXT NOT NULL, author_id INTEGER, created_at TEXT, FOREIGN KEY(author_id) REFERENCES users(id))')
    # seed admin
    admin_user = ('admin','adminpass')
    try:
        c.execute('INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)', (admin_user[0], generate_password_hash(admin_user[1]), 'admin', datetime.utcnow().isoformat()))
    except Exception:
        pass
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
