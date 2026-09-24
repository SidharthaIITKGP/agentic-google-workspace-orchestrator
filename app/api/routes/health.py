from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Report only the health of the FastAPI process."""
    return {"status": "ok"}
