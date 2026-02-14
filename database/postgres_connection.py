from hephaestus.settings import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(settings.PG_CONNECTION_STRING)
Session = sessionmaker(bind=engine)
session = Session()