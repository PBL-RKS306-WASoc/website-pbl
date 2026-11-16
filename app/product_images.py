import os
from io import BytesIO

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

PRODUCT_IMAGE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}
MAX_PRODUCT_IMAGE_DIMENSION = 4096


def product_image_directory():
    folder = current_app.config["UPLOAD_FOLDER"]
    if not os.path.isabs(folder):
        folder = os.path.join(os.path.dirname(current_app.root_path), folder)
    return os.path.join(folder, "products")


def process_product_image(upload):
    extension = os.path.splitext(upload.filename or "")[1].lower()
    expected_format = PRODUCT_IMAGE_FORMATS.get(extension)
    if not expected_format:
        return None, "Format foto produk harus JPG atau PNG."

    try:
        image = Image.open(upload.stream)
        if image.format != expected_format:
            return None, "Isi berkas tidak sesuai dengan ekstensi JPG atau PNG."
        image = ImageOps.exif_transpose(image)
        if (
            image.width > MAX_PRODUCT_IMAGE_DIMENSION
            or image.height > MAX_PRODUCT_IMAGE_DIMENSION
        ):
            return None, "Ukuran foto maksimal 4096 x 4096 piksel."

        output = BytesIO()
        if expected_format == "JPEG":
            image.convert("RGB").save(output, format="JPEG", optimize=True)
            extension = ".jpg"
        else:
            image.convert("RGBA").save(output, format="PNG", optimize=True)
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        return None, "Berkas foto produk bukan gambar yang valid."

    return (output.getvalue(), extension), None
