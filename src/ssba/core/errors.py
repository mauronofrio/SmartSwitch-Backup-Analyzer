class UnsupportedBackupError(Exception):
    """Raised when a backup (or a required file within it) doesn't match
    the supported no-password Smart Switch format."""
