import logging

from hephaestus.logging import init_logger


init_logger()

logger = logging.getLogger(__name__)

logger.info("Hello from dionysus!")