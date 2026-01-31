"""
Budget Automation System

An intelligent budgeting system that learns from historical spending patterns
to automatically categorize transactions with 90%+ accuracy.
"""

__version__ = "1.0.0"
__author__ = "Andrew"

# Expose main classes for easy imports
from .merchant_normalizer import normalize_merchant
from .rule_matcher import RuleMatcher
from .categorization_orchestrator import CategorizationOrchestrator

__all__ = [
    'normalize_merchant',
    'RuleMatcher',
    'CategorizationOrchestrator',
]
