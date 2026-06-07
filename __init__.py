"""Football ML Betting System - Source Package.

This package provides machine learning models, data pipelines, and evaluation
tools for football betting analysis.
"""

import logging
from typing import List

__version__: str = "1.0.0"
__author__: str = "Principal Software Engineer"
__all__: List[str] = []

# Configure structured logging format adhering to SRE observability standards
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s:%(filename)s:%(lineno)d] - %(message)s"
logging.basicConfig(format=LOG_FORMAT)

# Set up package-level logger with a NullHandler to prevent "No handler found"
# warnings in downstream applications, maintaining clean separation of concerns.
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())