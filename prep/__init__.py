from .vector import process_raster_logo, process_svg_input, VectorResult
from .raster import process_photo, RasterResult
from .passthrough import read_size, plt_to_polylines, render_file_preview, scale_to_dxf

RASTER_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
VECTOR_EXT = {".svg"}
PASSTHROUGH_EXT = {".dxf", ".plt"}  # sudah vektor / siap import

__all__ = [
    "process_raster_logo",
    "process_svg_input",
    "process_photo",
    "VectorResult",
    "RasterResult",
    "read_size",
    "plt_to_polylines",
    "render_file_preview",
    "scale_to_dxf",
    "RASTER_EXT",
    "VECTOR_EXT",
    "PASSTHROUGH_EXT",
]
