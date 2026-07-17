from io import BytesIO

from PIL import Image

from photo_hub.images import normalize_jpeg, tv_canvas_jpeg


def sample_png(width=300, height=600):
    image = Image.new("RGB", (width, height), (240, 40, 30))
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def test_normalize_jpeg_outputs_jpeg():
    data = normalize_jpeg(sample_png())
    assert data.startswith(b"\xff\xd8")


def test_tv_canvas_outputs_16_by_9_jpeg():
    data = tv_canvas_jpeg(sample_png(), width=1600, height=900)
    image = Image.open(BytesIO(data))
    assert image.size == (1600, 900)
    assert image.format == "JPEG"


def test_tv_canvas_crops_horizontal_images_to_fill():
    data = tv_canvas_jpeg(sample_png(width=1200, height=800), width=1600, height=900)
    image = Image.open(BytesIO(data))
    assert image.size == (1600, 900)
    assert image.getpixel((0, 0))[0] > 220
