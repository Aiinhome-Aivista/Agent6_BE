from fastapi import APIRouter, HTTPException
from database.connection import fetch_all

router = APIRouter(
    prefix="/roles",
    tags=["Roles"]
)

@router.get("/")
async def get_roles():
    """Fetch all available roles using Stored Procedure."""
    try:
        # Calling the Stored Procedure we created
        roles = fetch_all("CALL sp_get_roles()")
        return roles
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
