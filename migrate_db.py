import sqlite3
import os

def migrate_database(db_path='data.db'):
    """Add new columns to existing pitches table"""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Get existing columns
    c.execute("PRAGMA table_info(pitches)")
    existing_columns = [column[1] for column in c.fetchall()]
    
    # Define new columns to add
    new_columns = {
        'category': 'TEXT',
        'tags': 'TEXT',
        'image': 'TEXT',
        'funding_goal': 'TEXT',
        'stage': 'TEXT',
        'team_size': 'TEXT',
        'location': 'TEXT',
        'website': 'TEXT',
        'demo_url': 'TEXT',
        'looking_for': 'TEXT'
    }
    
    # Add missing columns
    for column_name, column_type in new_columns.items():
        if column_name not in existing_columns:
            try:
                c.execute(f'ALTER TABLE pitches ADD COLUMN {column_name} {column_type}')
                print(f'Added column: {column_name}')
            except Exception as e:
                print(f'Error adding column {column_name}: {e}')
    
    conn.commit()
    conn.close()
    print('Database migration completed!')

if __name__ == '__main__':
    migrate_database()
