from django.core.exceptions import ValidationError

MAX_PROFILE_PICTURE_BYTES = 5 * 1024 * 1024  # 5 MB


def validate_image_size(file):
    """
    Reject a newly uploaded image larger than MAX_PROFILE_PICTURE_BYTES.

    Only fresh uploads are checked. A picture that is already stored is left
    alone, so re-validating a user (admin, full_clean) never touches storage
    and cannot fail because the old file went missing.
    """
    if getattr(file, "_committed", True):
        return
    if file.size > MAX_PROFILE_PICTURE_BYTES:
        limit_mb = MAX_PROFILE_PICTURE_BYTES / (1024 * 1024)
        raise ValidationError(
            "Image is too large (%(size).1f MB). The maximum size is %(limit).0f MB.",
            code="file_too_large",
            params={"size": file.size / (1024 * 1024), "limit": limit_mb},
        )
