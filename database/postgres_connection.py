from hephaestus.settings import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from langgraph.checkpoint.postgres import PostgresSaver

BASEURL = settings.PG_CONNECTION_STRING

ALCHEMY_CONNECTION_STRING = BASEURL+settings.ALCHEMY_DB
CHECKPOINT_CONNECTION_STRING = BASEURL+settings.CHECKPOINT_DB

Base = declarative_base()

engine = create_engine(ALCHEMY_CONNECTION_STRING)
Session = sessionmaker(bind=engine)
session = Session()


checkpointer = PostgresSaver.from_conn_string(CHECKPOINT_CONNECTION_STRING)