import os

DEBUG = os.getenv("DEBUG") == "1"
TRACE = os.getenv("TRACE") == "1"
PERF = os.getenv("PERF") == "1"
