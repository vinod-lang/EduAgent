"""Import-safe web presentation adapter; no automatic server/storage lifecycle."""
def create_api_app(**options):
    from .app import create_api_app as factory
    return factory(**options)
