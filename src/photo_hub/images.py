"""Image normalization and Samsung TV canvas generation."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageFilter, ImageOps


class ImageProcessingError(RuntimeError):
    """Image cannot be decoded or transformed."""


def register_heif() -> None:
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return
    register_heif_opener()


def open_image(data: bytes) -> Image.Image:
    register_heif()
    try:
        image = Image.open(BytesIO(data))
        image.load()
    except Exception as exc:
        raise ImageProcessingError("Could not decode image attachment.") from exc
    return ImageOps.exif_transpose(image).convert("RGB")


def to_jpeg_bytes(image: Image.Image, quality: int = 92) -> bytes:
    output = BytesIO()
    image.save(output, "JPEG", quality=quality, optimize=True)
    return output.getvalue()


def normalize_jpeg(data: bytes) -> bytes:
    return to_jpeg_bytes(open_image(data))


def tv_canvas_jpeg(data: bytes, width: int = 3840, height: int = 2160) -> bytes:
    image = open_image(data)
    if image.width > image.height:
        cropped = ImageOps.fit(
            image,
            (width, height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        return to_jpeg_bytes(cropped, quality=93)

    canvas_ratio = width / height
    image_ratio = image.width / image.height

    if image_ratio > canvas_ratio:
        contained_width = width
        contained_height = round(width / image_ratio)
    else:
        contained_height = height
        contained_width = round(height * image_ratio)

    contained = image.resize((contained_width, contained_height), Image.Resampling.LANCZOS)
    fill = image.resize((width, height), Image.Resampling.LANCZOS).filter(
        ImageFilter.GaussianBlur(radius=42)
    )
    overlay = Image.new("RGB", (width, height), (0, 0, 0))
    overlay.putalpha(70)
    fill = Image.alpha_composite(fill.convert("RGBA"), overlay).convert("RGB")
    x = (width - contained_width) // 2
    y = (height - contained_height) // 2
    fill.paste(contained, (x, y))
    return to_jpeg_bytes(fill, quality=93)
