#!/usr/bin/env bash
set -euo pipefail

echo "setting up nexus..."

command -v python3 >/dev/null 2>&1 || { echo "Python 3.12+ required"; exit 1; }
command -v cargo   >/dev/null 2>&1 || { echo "Rust (stable) required — https://rustup.rs"; exit 1; }
command -v uv      >/dev/null 2>&1 || { echo "uv required — https://docs.astral.sh/uv/"; exit 1; }
command -v bun     >/dev/null 2>&1 || { echo "bun required — https://bun.sh"; exit 1; }

echo "dependencies found"
uv sync
cargo build -p nexus-core-rs
cd web/frontend && bun install && cd ../..

echo ""
echo "nexus is ready."
echo "copy .env.example to .env, fill in tokens, then: make dev"
