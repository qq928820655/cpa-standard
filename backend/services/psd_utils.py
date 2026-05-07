"""
PSD enhancement stub.
"""
from pathlib import Path
from typing import Optional

LAYERED_PSD_DEPENDENCY_ERROR = "PSD enhancement package is not installed"


def save_image_as_psd(image_path: Path, output_path: Path) -> Path:
    """Raise when enhancement package is missing."""
    raise RuntimeError(LAYERED_PSD_DEPENDENCY_ERROR)


def save_layered_psd(image_path: Path, output_path: Path) -> Path:
    """Raise when enhancement package is missing."""
    raise RuntimeError(LAYERED_PSD_DEPENDENCY_ERROR)


def save_semantic_psd_with_fallback(image_path: Path, output_path: Path) -> Path:
    """Raise when enhancement package is missing."""
    raise RuntimeError(LAYERED_PSD_DEPENDENCY_ERROR)


async def convert_result_to_psd(result_id: int, db) -> Optional[Path]:
    """Raise when enhancement package is missing."""
    raise RuntimeError(LAYERED_PSD_DEPENDENCY_ERROR)
