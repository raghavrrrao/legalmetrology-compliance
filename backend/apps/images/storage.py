"""Safe storage paths for uploaded images.

The uploaded filename is attacker-controlled. It is recorded verbatim as
`ProductImage.original_filename` for display, but it is never used to build a
path on disk. Instead every stored file gets a fresh random name, which
eliminates path traversal, collisions, and Windows reserved device names
(`CON`, `NUL`, `LPT1`) in one step rather than by trying to sanitise them.
"""

import re
import unicodedata
import uuid
from datetime import date
from pathlib import PurePosixPath

#: Filenames longer than this are truncated before being stored for display.
MAX_DISPLAY_FILENAME_LENGTH = 255

_UNSAFE_DISPLAY_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitise_display_filename(filename: str) -> str:
    """Return a filename safe to store and echo back in an API response.

    This protects the *display* path, not the filesystem - the stored file
    never uses this value. It strips any directory component, removes control
    characters (which can forge log lines and confuse terminals), normalises
    Unicode so visually identical names compare equal, and caps the length.
    """
    if not filename:
        return "unnamed"

    # Take the last segment under both separator conventions: a Windows client
    # can send "C:\Users\x\photo.jpg" and PurePosixPath would keep it whole.
    candidate = filename.replace("\\", "/")
    candidate = PurePosixPath(candidate).name

    candidate = unicodedata.normalize("NFKC", candidate)
    candidate = _UNSAFE_DISPLAY_CHARS.sub("", candidate)
    candidate = candidate.strip().strip(".")

    if not candidate:
        return "unnamed"
    return candidate[:MAX_DISPLAY_FILENAME_LENGTH]


def product_image_upload_path(instance, filename: str) -> str:
    """Build the storage path for a `ProductImage` file field.

    Returns `product-images/<YYYY>/<MM>/<uuid><ext>`. The date prefix keeps
    directories from growing without bound, which matters on filesystems that
    degrade with very large flat directories.

    `filename` is deliberately ignored except for its extension, and even that
    is validated against an allowlist first - so an upload named
    `../../settings.py` or `x.php` cannot influence where or as what it lands.
    """
    from apps.images.constants import extension_for_upload

    extension = extension_for_upload(filename)
    today = date.today()
    return str(
        PurePosixPath("product-images")
        / f"{today.year:04d}"
        / f"{today.month:02d}"
        / f"{uuid.uuid4().hex}{extension}"
    )
