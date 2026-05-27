"""Sample module for testing codemapper parser.

This is the second line of the docstring and should NOT appear in module_doc.
"""
import os
import sys
from pathlib import Path
from dataclasses import dataclass
import requests
from . import utils  # noqa: F401 — relative import

CONSTANT_A = 42
CONSTANT_B: str = "hello"
not_a_constant = "lower"  # should NOT be detected as constant


@dataclass
class Animal:
    name: str
    species: str

    def speak(self) -> str: ...
    def _private(self, x: int) -> None: ...


class Vehicle:
    def __init__(self, speed: int, fuel: str = "gas") -> None:
        self.speed = speed

    @classmethod
    def from_dict(cls, d: dict) -> "Vehicle": ...


def standalone_function(x: int, y: float = 0.0) -> str: ...


async def async_func(items: list[str]) -> None: ...
