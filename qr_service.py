"""
BloodConnect — QR Code Generation Service
Encodes ONLY the secure URL linking to the donor's tokenized profile page.
Does NOT store personal identifiable information (name, phone, email) inside the QR code matrix.
"""

import io
import base64
import qrcode
from qrcode.constants import ERROR_CORRECT_M


def generate_qr_png_bytes(target_url: str) -> bytes:
    """
    Generates a PNG byte stream of a QR code pointing to target_url.
    Uses BloodConnect crimson red foreground on white background.
    """
    qr = qrcode.QRCode(
        version=None,  # Auto-size based on content
        error_correction=ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(target_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#DC2626", back_color="#FFFFFF")
    buffer = io.BytesIO()
    img.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def generate_qr_base64_data_url(target_url: str) -> str:
    """
    Generates an inline base64 data URL for direct embedding into HTML templates.
    """
    png_bytes = generate_qr_png_bytes(target_url)
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"
