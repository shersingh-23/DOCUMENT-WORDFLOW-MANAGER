import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

DB_NAME = 'database.db'

def connect_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = connect_db()
    c = conn.cursor()
    
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT CHECK(role IN ('creator', 'reviewer')) NOT NULL,
            status TEXT DEFAULT 'active'
        )
    ''')
    
    # Documents table
    c.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            author_id INTEGER,
            status TEXT CHECK(status IN ('draft', 'review', 'approved', 'rejected')) NOT NULL DEFAULT 'draft',
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (author_id) REFERENCES users(id)
        )
    ''')
    
    # Comments table
    c.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            author TEXT,
            comment TEXT,
            created_at TEXT,
            FOREIGN KEY (document_id) REFERENCES documents(id)
        )
    ''')


    # Document Versions table
    c.execute('''
        CREATE TABLE IF NOT EXISTS document_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            version_number INTEGER,
            content TEXT,
            updated_at TEXT,
            FOREIGN KEY (document_id) REFERENCES documents(id)
        )
    ''')


    conn.commit()
    conn.close()

def get_user_by_email(email):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE email = ?', (email,))
    user = cur.fetchone()
    conn.close()
    return user

def add_user(name, email, password, role='creator'):
    conn = connect_db()
    cur = conn.cursor()
    hashed_pw = generate_password_hash(password)
    cur.execute('INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)', (name, email, hashed_pw, role))
    conn.commit()
    conn.close()

def verify_password(hashed_password, input_password):
    return check_password_hash(hashed_password, input_password)

def is_admin(email, password):
    # Hardcoded admin for simplicity
    admin_email = 'admin@docuflow.com'
    admin_password = 'admin123'
    return email == admin_email and password == admin_password


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
