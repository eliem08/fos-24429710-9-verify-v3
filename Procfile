web: uvicorn app:app --host 0.0.0.0 --port $PORT
worker: python -m invoiceledger.cli daemon --interval 60
