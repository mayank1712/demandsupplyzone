"""Price data providers. Each returns a DataFrame indexed by IST datetime
with columns: open, high, low, close, volume."""
from .. import config

_provider = None


def get_provider():
    global _provider
    if _provider is None:
        if config.DATA_PROVIDER == "yahoo":
            from .yahoo import YahooProvider
            _provider = YahooProvider()
        else:
            from .dhan import DhanProvider
            _provider = DhanProvider(config.DHAN_CLIENT_ID, config.DHAN_ACCESS_TOKEN)
    return _provider
