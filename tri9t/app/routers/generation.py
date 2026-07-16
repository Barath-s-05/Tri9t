"""QA generation router (placeholder)."""

from fastapi import APIRouter

router = APIRouter(prefix="/generate", tags=["generation"])


@router.post("/test-cases")
async def generate_test_cases() -> dict[str, str]:
    """Generate QA test cases via LLM (Stage 4+).

    Returns:
        Placeholder response.
    """
    return {"message": "Generation endpoint — not yet implemented"}
