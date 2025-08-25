import sqlite3

DB_NAME = "jobs.db"

def create_connection():
    return sqlite3.connect(DB_NAME)

def create_table():
    conn = create_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        site TEXT,
        title TEXT,
        company TEXT,
        link TEXT,
        scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()

def insert_job(site, title, company, link):
    conn = create_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO jobs (site, title, company, link)
    VALUES (?, ?, ?, ?)
    """, (site, title, company, link))

    conn.commit()
    conn.close()