from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
import os

# We define the tokenUrl just for swagger UI docs
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
SECRET_KEY = os.getenv("SECRET_KEY", "secret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Dependency to get the current user from the JWT token.
    Decodes the token and returns the user's ID and Role.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        role_id: int = payload.get("role_id")
        if user_id is None:
            raise credentials_exception
        return {"user_id": user_id, "id": user_id, "role_id": role_id, "username": payload.get("sub")}
    except JWTError:
        raise credentials_exception
