"""The Client Library: provenance-carrying records the writer reads from.

`store` holds the read/write logic so the router stays thin and the enrichment
pipeline can consult exclusions without importing a web module.
"""
from . import store  # noqa: F401
