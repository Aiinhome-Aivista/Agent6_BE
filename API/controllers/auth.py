from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from database.connection import fetch_one, execute
from utils.security import get_password_hash, verify_password, create_access_token

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str
    role_id: int

class UserLogin(BaseModel):
    username: str
    password: str

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user: UserRegister):
    # 1. Check if user already exists
    existing_user = fetch_one("SELECT id FROM users WHERE username = %s OR email = %s", (user.username, user.email))
    if existing_user:
        raise HTTPException(status_code=400, detail="Username or email already registered")
    
    # 2. Check if role exists
    role = fetch_one("SELECT id FROM roles WHERE id = %s", (user.role_id,))
    if not role:
        raise HTTPException(status_code=400, detail="Invalid role ID. Valid roles are 1 to 5.")

    # 3. Hash the password
    hashed_password = get_password_hash(user.password)

    # 4. Insert into the database using Stored Procedure
    try:
        # execute will run the SP and we get the inserted ID
        user_id = execute("CALL sp_register_user(%s, %s, %s, %s)", (user.username, user.email, hashed_password, user.role_id))
        return {"message": "User registered successfully", "user_id": user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.post("/login")
async def login(user: UserLogin):
    # 1. Fetch user by username
    db_user = fetch_one("SELECT id, username, email, hashed_password, role_id FROM users WHERE username = %s", (user.username,))
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # 2. Verify password
    if not verify_password(user.password, db_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # 3. Create JWT token
    access_token = create_access_token(
        data={"sub": db_user["username"], "user_id": db_user["id"], "role_id": db_user["role_id"]}
    )
    
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "user": {
            "id": db_user["id"],
            "username": db_user["username"],
            "email": db_user["email"],
            "role_id": db_user["role_id"]
        }
    }

@router.get("/users")
async def get_all_users():
    try:
        from database.connection import fetch_all
        users = fetch_all("SELECT u.id, u.username, u.email, r.name as role, u.is_active, u.created_at FROM users u JOIN roles r ON u.role_id = r.id")
        return users
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/audit")
async def get_audit_logs():
    try:
        from database.connection import fetch_all
        logs = fetch_all("SELECT a.id, COALESCE(u.username, 'System') as username, a.action, a.details, a.created_at FROM audit_logs a LEFT JOIN users u ON a.user_id = u.id ORDER BY a.created_at DESC LIMIT 100")
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
