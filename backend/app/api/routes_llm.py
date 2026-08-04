from fastapi import APIRouter

router = APIRouter()


@router.post("/recommendations")
async def get_recommendations():
    return {"message": "LLM recommendations endpoint"}
