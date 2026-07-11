"""Puffin Copilot — AI-first chat frontend for the Puffin fine-tuning platform.

Two packages:

  copilot.backend  — FastAPI server. Anthropic SDK with tool-use loop that
                     exposes the entire llmops platform as typed tools.
                     SSE streaming, SQLite thread persistence.

  copilot.frontend — Next.js 15 app. Lives at copilot/frontend/ on disk;
                     not a Python package. Built with `npm run build` and
                     served by Next.js in dev, or via the FastAPI app's
                     static-mount in production.
"""
__version__ = "0.1.0"
