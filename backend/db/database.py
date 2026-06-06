from sqlmodel import SQLModel, create_engine, Session

# This creates a local SQLite file called inventory.db in your project
# SQLite is a simple file-based database — perfect for a hackathon
# no server needed, it just works
DATABASE_URL = "sqlite:///./inventory.db"

# The engine is the connection to the database
# connect_args is a SQLite-specific setting that prevents threading issues with FastAPI
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def create_db():
    # This reads all your SQLModel classes and creates the tables if they don't exist yet
    # You call this once when the app starts
    SQLModel.metadata.create_all(engine)

def get_session():
    # This is a dependency FastAPI will use to give each request its own database session
    # 'with' ensures the session is always closed after the request, even if it crashes
    with Session(engine) as session:
        yield session