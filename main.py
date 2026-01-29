import logging

from hephaestus.logging.init_logging import init_logging


init_logging()

logger = logging.getLogger(__name__)

logger.info("Hello from dionysus!")