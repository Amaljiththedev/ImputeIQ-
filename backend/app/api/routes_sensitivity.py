from fastapi import APIRouter

router = APIRouter()


@router.post("/")
async def run_sensitivity_analysis():
    return {"message": "Sensitivity analysis endpoint"}
