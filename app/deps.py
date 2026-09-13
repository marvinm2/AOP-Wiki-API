"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.data import DataService


def get_data(request: Request) -> DataService:
    return request.app.state.data
