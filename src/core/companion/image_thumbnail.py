"""공개 허용된 정지 사진 사본만 제한된 썸네일로 변환한다."""

import base64
from io import BytesIO

from PIL import Image

from .input_uploads import InputError


def thumbnail(data_url):
    if not isinstance(data_url, str) or len(data_url) > 4 * ((4194304 + 2) // 3) + 32:
        raise InputError("image_unavailable", 404)
    try:
        header, encoded = data_url.split(",", 1)
        if header not in {"data:image/png;base64", "data:image/jpeg;base64"}:
            raise ValueError()
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(raw)) as source:
            if (source.format not in {"PNG", "JPEG"} or getattr(source, "n_frames", 1) != 1
                    or not 0 < source.width <= 2048 or not 0 < source.height <= 2048):
                raise ValueError()
            format = source.format
            source.thumbnail((320, 320), Image.Resampling.LANCZOS)
            # 별도 픽셀 사본으로 EXIF·텍스트 청크를 전파하지 않는다.
            pixels = Image.new("RGBA" if format == "PNG" else "RGB", source.size)
            pixels.paste(source)
        try:
            while True:
                output = BytesIO()
                pixels.save(output, format, quality=85)
                body = output.getvalue()
                if len(body) <= 128 * 1024:
                    return body, "image/png" if format == "PNG" else "image/jpeg"
                pixels.thumbnail((max(1, pixels.width * 3 // 4), max(1, pixels.height * 3 // 4)), Image.Resampling.LANCZOS)
        finally:
            pixels.close()
    except InputError:
        raise
    except Exception:
        raise InputError("image_unavailable", 404) from None
