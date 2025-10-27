import sqlite3
import os

def add_notifications_table(db_path='data.db'):
    """Add notifications table to the database"""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Notifications table
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        related_id INTEGER,
        related_type TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )''')

    # Create index for faster queries
    c.execute('''CREATE INDEX IF NOT EXISTS idx_notifications_user_id
                 ON notifications(user_id)''')

    c.execute('''CREATE INDEX IF NOT EXISTS idx_notifications_is_read
                 ON notifications(is_read)''')

    c.execute('''CREATE INDEX IF NOT EXISTS idx_notifications_created_at
                 ON notifications(created_at DESC)''')

    conn.commit()
    conn.close()
    print('Notifications table created successfully!')

if __name__ == '__main__':
    add_notifications_table()
