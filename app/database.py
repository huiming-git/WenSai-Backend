from sqlalchemy.orm import sessionmaker
from sqlmodel import create_engine

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
