"""Regression Test Generator — module 12 of the architecture."""

from .generator import SUITE_VERSION, RegressionCase, RegressionGenerator
from .runner import CheckOutcome, RegressionRunner, load_suite

__all__ = [
    "SUITE_VERSION",
    "CheckOutcome",
    "RegressionCase",
    "RegressionGenerator",
    "RegressionRunner",
    "load_suite",
]
