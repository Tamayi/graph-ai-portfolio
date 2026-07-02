"""Entry point: run the FastAPI backend, which serves the API and the frontend.

    uv run main.py
then open http://localhost:8007
"""
from __future__ import annotations

import uvicorn

# Port for the FastAPI backend. Change here to move the whole app.
PORT = 8007


def main() -> None:
    uvicorn.run("app.api:app", host="127.0.0.1", port=PORT, reload=True)


if __name__ == "__main__":
    main()
