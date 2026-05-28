"""Validation helpers for minilogue xd data."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .constants import PRODUCT_NAME, PROGRAM_SIGNATURE, PROGRAM_SIZE


def validate_prog_bin(prog_bin: bytes) -> None:
    if len(prog_bin) != PROGRAM_SIZE:
        raise ValueError(f"Invalid program size: expected {PROGRAM_SIZE}, got {len(prog_bin)}")
    if not prog_bin.startswith(PROGRAM_SIGNATURE):
        raise ValueError("Invalid program signature")


def validate_product(root: ET.Element) -> None:
    product = root.findtext("Product", default="").strip()
    if product != PRODUCT_NAME:
        raise ValueError(f"Unsupported product: {product or 'missing'}")
