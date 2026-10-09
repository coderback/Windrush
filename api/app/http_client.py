"""
httpx client factories that share one TLS context.

httpx builds a fresh SSLContext for every Client/AsyncClient, which loads the whole CA bundle
synchronously (~0.5–1s). Inside async code that stalls the event loop for every request in
the process — and live job discovery alone creates ~70 clients. Building the context once,
at import (i.e. startup), makes client construction ~0.1ms. SSLContext is safe to share.
"""
import ssl

import certifi
import httpx

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def async_client(**kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(verify=SSL_CONTEXT, **kwargs)


def client(**kwargs) -> httpx.Client:
    return httpx.Client(verify=SSL_CONTEXT, **kwargs)
