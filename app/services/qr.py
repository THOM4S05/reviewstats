from io import BytesIO

import qrcode


def make_qr_png(url: str) -> bytes:
    image = qrcode.make(url)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()

