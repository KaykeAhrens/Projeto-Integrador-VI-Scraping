import sqlite3
from database.db import DB_NAME
from datetime import datetime

def query_jobs(limit=10):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT site, title, company, link, scraped_at
        FROM jobs
        ORDER BY scraped_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def format_job(row):
    site, title, company, link, scraped_at = row
    scraped_at = datetime.strptime(scraped_at, "%Y-%m-%d %H:%M:%S")
    scraped_at_str = scraped_at.strftime("%d/%m/%Y %H:%M:%S")
    
    output = f"""
[{site}] {title}
Empresa: {company}
Link: {link}
Coletada em: {scraped_at_str}
{'-'*80}
"""
    return output.strip()

if __name__ == "__main__":
    results = query_jobs(20)  # pega 20 últimas vagas
    for r in results:
        print(format_job(r))
