import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# The schema belongs to db/migrations: this app maps onto it and never creates tables
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
