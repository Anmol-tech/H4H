"""
Utility to convert each page of a PDF into a PNG image.

Uses pdf2image (poppler-based) for high-quality rendering.

Usage:
    from services.utils import pdf_to_images

    # From a file path
    images = pdf_to_images("/path/to/form.pdf")

    # From raw bytes
    images = pdf_to_images(pdf_bytes)

Returns a list of dicts, one per page:
    [{"page": 1, "path": Path("...page_1.png")}, ...]
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Union

from pdf2image import convert_from_bytes, convert_from_path


def pdf_to_images(
    source: Union[str, Path, bytes],
    output_dir: Union[str, Path, None] = None,
    dpi: int = 200,
    fmt: str = "png",
    prefix: str = "page",
) -> list[dict]:
    """Convert every page of a PDF to a PNG image.

    Args:
        source:     File path (str / Path) or raw PDF bytes.
        output_dir: Directory to save images. If None a temp directory is used.
        dpi:        Resolution for rendering (default 200).
        fmt:        Image format – "png" (default), "jpeg", etc.
        prefix:     Filename prefix for saved images.

    Returns:
        A list of dicts with keys:
            - page  (int):  1-based page number
            - path  (Path): absolute path to the saved image
            - image (PIL.Image.Image): the in-memory PIL image
    """
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="pdf_images_"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    # Convert PDF → list of PIL Images
    if isinstance(source, (str, Path)):
        images = convert_from_path(str(source), dpi=dpi)
    elif isinstance(source, bytes):
        images = convert_from_bytes(source, dpi=dpi)
    else:
        raise TypeError(
            f"source must be a file path (str/Path) or bytes, got {type(source).__name__}"
        )

    results: list[dict] = []
    for idx, img in enumerate(images, start=1):
        filename = f"{prefix}_{idx}.{fmt}"
        filepath = output_dir / filename
        img.save(str(filepath), fmt.upper())
        results.append({"page": idx, "path": filepath, "image": img})

    return results
