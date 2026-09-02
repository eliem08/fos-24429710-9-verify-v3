"""ASGI Entrypoint for InvoiceLedger Server."""

import os
import sys
from invoiceledger.server import app

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    reload_flag = "--reload" in sys.argv
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))

    if reload_flag:
        uvicorn.run("app:app", host=host, port=port, reload=True)
    else:
        uvicorn.run(app, host=host, port=port, reload=False, workers=workers if workers > 1 else None)

