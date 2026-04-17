"""PDF watermark selection and removal helpers."""

from .processor import SelectionProfile, WatermarkRegion, batch_remove_watermarks

__all__ = [
    "SelectionProfile",
    "WatermarkRegion",
    "batch_remove_watermarks",
]
