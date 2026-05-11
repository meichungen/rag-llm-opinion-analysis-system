import pymysql
import os
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

def create_database():
    db_url = os.getenv('DATABASE_URL', 'mysql+pymysql://root:123456@localhost:3306/social_media_analysis')
    
    # Parse the URL
    # Format: mysql+pymysql://user:pass@host:port/dbname
    if '://' not in db_url:
        print("Invalid DATABASE_URL format")
        return

    try:
        url = urlparse(db_url)
        username = url.username
        password = url.password
        hostname = url.hostname
        port = url.port or 3306
        database = url.path.lstrip('/')
        
        print(f"Connecting to MySQL at {hostname}:{port} as {username}...")
        
        # Connect to MySQL server (no DB selected yet)
        conn = pymysql.connect(
            host=hostname,
            user=username,
            password=password,
            port=port,
            charset='utf8mb4'
        )
        
        try:
            with conn.cursor() as cursor:
                # Check if database exists
                cursor.execute(f"SHOW DATABASES LIKE '{database}'")
                result = cursor.fetchone()
                
                if not result:
                    print(f"Database '{database}' does not exist. Creating...")
                    cursor.execute(f"CREATE DATABASE {database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                    print(f"Database '{database}' created successfully.")
                else:
                    print(f"Database '{database}' already exists.")
                    
        finally:
            conn.close()
            
    except Exception as e:
        print(f"Error initializing database: {e}")
        print("Please check your .env file and ensure MySQL is running and credentials are correct.")

if __name__ == '__main__':
    create_database()
