#!/bin/bash
cd "$(dirname "$0")"
exec docker compose up --abort-on-container-exit --exit-code-from app
