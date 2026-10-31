"""Run the real backend with in-memory MongoDB (mongomock). Test harness only.

Run from backend/: python ../scripts/e2e/run_backend_inmemory.py
"""
import os, sys
import mongomock, pymongo
pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("MONGODB_URI", "mongodb://inmemory")
os.environ.setdefault("JWT_SECRET", "x" * 48)
sys.path.insert(0, os.getcwd())
import main
main.MongoClient = mongomock.MongoClient
import uvicorn
uvicorn.run(main.app, host="127.0.0.1", port=8001)
