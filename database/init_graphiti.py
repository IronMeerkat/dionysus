from hephaestus.settings import settings
from graphiti import Graphiti

graphiti = Graphiti(
    uri=settings.NEO4J.NEO4J_URI,
    user=settings.NEO4J.NEO4J_USER,
    password=settings.NEO4J.NEO4J_PASSWORD,
)
