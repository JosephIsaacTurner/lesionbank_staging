# db_session.py

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
import environ
from pathlib import Path
from sqlalchemy.engine.url import URL

# Initialize environ
env = environ.Env()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Read .env file
environ.Env.read_env(str(BASE_DIR / '.env'))

# If running locally, use sqlite3 (uncomment the following lines)
# engine = create_engine(f'sqlite:////{BASE_DIR}/db.sqlite3')
# SessionFactory = sessionmaker(bind=engine)
# Session = scoped_session(SessionFactory)

# If running with postgres, uncomment the following lines
db_name = env('POSTGRES_DB')
db_username = env('POSTGRES_USER')
db_host = env('POSTGRES_HOST')
db_port = env('POSTGRES_PORT')
db_password = env('POSTGRES_PASSWORD')
db_schema = env('POSTGRES_SCHEMA')

# Construct the database URL with connect_args
database_url = URL.create(
    drivername='postgresql',
    username=db_username,
    password=db_password,
    host=db_host,
    port=db_port,
    database=db_name,
    query={
        'options': f'-c search_path={db_schema}'
    }
)

# Create the PostgreSQL engine with connect_args
engine = create_engine(
    database_url,
    echo=False  # Optional: enables SQL query logging for debugging
)

# Ensure the schema is set for every new connection
@event.listens_for(engine, "connect")
def set_search_path(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute(f"SET search_path TO {db_schema}")
    cursor.close()

# Create session factory and scoped session
SessionFactory = sessionmaker(bind=engine)
Session = scoped_session(SessionFactory)

# Functions to get the session and engine
def get_session():
    """
    Get a new session with the scoped_session factory.
    """
    return Session()

def get_engine():
    """
    Get the configured SQLAlchemy engine.
    """
    return engine