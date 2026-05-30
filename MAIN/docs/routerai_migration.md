# RouterAI Migration

## Overview

All AI model requests have been migrated from **GPTunnel** (`https://gptunnel.ru/v1`) to **RouterAI** (`https://routerai.ru/api/v1`).

## Changes Made

### 1. Configuration (`config.py`)

- `ROUTERAI_API_KEY` environment variable added (with fallback to `DEEPSEEK_API_KEY`)
- `client` now uses `ROUTERAI_API_KEY` and `https://routerai.ru/api/v1` as base URL
- `ROUTERAI_BASE_URL` constant introduced for reuse

### 2. Services (`services/ai.py`)

- Vision client updated to use `ROUTERAI_API_KEY` and RouterAI endpoint
- Audio transcription model changed from `gemini-2.0-flash` to `google/gemini-2.0-flash` (RouterAI-valid prefix)

### 3. Tariffs (`tariffs.py`)

Models renamed to RouterAI-compatible identifiers:

| Old (GPTunnel) | New (RouterAI) |
|---|---|
| `deepseek-v4-flash` | `deepseek/deepseek-chat` |
| `gemini-3.1-flash-lite` | `google/gemini-2.0-flash-lite` |
| `gemini-3-flash` | `google/gemini-2.0-flash` |
| `gpt-4o-mini` | `openai/gpt-4o-mini` |

### 4. Utility Script (`get_models.py`)

- Changed to connect to RouterAI endpoint
- Uses `ROUTERAI_API_KEY` with fallback to `DEEPSEEK_API_KEY`

## Environment Variables

Add this to your `.env` file:


