from importlib.metadata import version, PackageNotFoundError


def get_version() -> str:
    try:
        return version('polyglav')
    except PackageNotFoundError:
        return 'unknown'
