#!/usr/bin/env bash
set -e

python -m py_compile \
  main.py \
  database.py \
  keyboards.py \
  survey.py \
  admin_handlers.py \
  callsign.py

exec python main.py
