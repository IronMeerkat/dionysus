from hephaestus.settings import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


BASEURL = settings.PG_CONNECTION_STRING

ALCHEMY_CONNECTION_STRING = BASEURL+settings.ALCHEMY_DB

Base = declarative_base()

engine = create_engine(ALCHEMY_CONNECTION_STRING)
Session = sessionmaker(bind=engine)
session = Session()
