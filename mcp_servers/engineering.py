"""Backward-compatible entry point; implementation lives in engineering_server."""

import sys
from mcp_servers import engineering_server as _server

if __name__ == "__main__":
    _server.run()
else:
    # Preserve legacy imports and monkeypatch behavior by aliasing the actual module.
    sys.modules[__name__] = _server
