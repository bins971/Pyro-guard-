from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from passlib.context import CryptContext
from pydantic import BaseModel
from typing import Optional
import jwt
import bcrypt

# Monkeypatch bcrypt for passlib compatibility with bcrypt >= 4.0.0
if not hasattr(bcrypt, "__about__"):
    class _About:
        __version__ = "3.2.2"
    bcrypt.__about__ = _About

from datetime import datetime, timedelta

from ..database import get_db
from ..models import User, AuditLog
from ..config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = settings.JWT_SECRET_KEY if hasattr(settings, "JWT_SECRET_KEY") else "YOUR_SUPER_SECRET_PYRO_GUARD_KEY_123"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


# ── Pydantic schemas ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    role: Optional[str] = "operator"

class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
    is_admin: bool
    role: str

class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: Optional[bool] = False
    role: Optional[str] = "operator"
    is_approved: Optional[bool] = True

class UserUpdate(BaseModel):
    is_admin: Optional[bool] = None
    role: Optional[str] = None
    is_approved: Optional[bool] = None

class PasswordResetRequest(BaseModel):
    new_password: str


# ── Helpers & Audit Logging ──────────────────────────────────────────────────

def log_audit(db: Session, username: str, action: str, details: str = None, user_id: int = None, ip_address: str = None):
    try:
        entry = AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            details=details,
            ip_address=ip_address
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Failed to record audit log: {e}")

def get_user_role(user: User) -> str:
    if user.role:
        return user.role.lower()
    return "admin" if user.is_admin else "operator"

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(authorization: str = Header(...), db: Session = Depends(get_db)) -> User:
    """Decode the Bearer token and return the current User row."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise credentials_exception
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    role = get_user_role(current_user)
    if not (current_user.is_admin or role == "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user

def require_operator_or_admin(current_user: User = Depends(get_current_user)) -> User:
    role = get_user_role(current_user)
    if role not in ["admin", "operator"] and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator or Admin privileges required")
    return current_user


# ── Public endpoints ─────────────────────────────────────────────────────────

@router.post("/login", response_model=Token)
def login(request: LoginRequest, req: Request, db: Session = Depends(get_db)):
    clean_username = request.username.strip().lower()
    user = db.query(User).filter(func.lower(User.username) == clean_username).first()
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.is_approved is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is pending administrator approval. Please ask an Admin to confirm your account access.",
        )
    role = get_user_role(user)
    is_admin = user.is_admin or (role == "admin")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "admin": is_admin, "role": role}, expires_delta=access_token_expires
    )

    client_ip = req.client.host if req.client else None
    log_audit(db, username=user.username, action="USER_LOGIN", details=f"Logged in with role '{role}'", user_id=user.id, ip_address=client_ip)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username,
        "is_admin": is_admin,
        "role": role,
    }


@router.post("/register")
def register(request: RegisterRequest, req: Request, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == request.username).first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")
    
    requested_role = (request.role or "operator").lower()
    if requested_role not in ["admin", "operator", "viewer"]:
        requested_role = "operator"

    new_user = User(
        username=request.username,
        hashed_password=get_password_hash(request.password),
        is_admin=(requested_role == "admin"),
        role=requested_role,
        is_approved=False  # Requires admin approval before login
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    client_ip = req.client.host if req.client else None
    log_audit(db, username=new_user.username, action="USER_REGISTER", details=f"Registered user requesting role '{requested_role}' (Pending Approval)", user_id=new_user.id, ip_address=client_ip)
    
    return {
        "message": "Account registered successfully. An administrator must confirm your account before you can log in.",
        "username": new_user.username,
        "role": requested_role,
        "is_approved": False
    }


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    role = get_user_role(current_user)
    return {
        "id": current_user.id,
        "username": current_user.username,
        "is_admin": current_user.is_admin or (role == "admin"),
        "role": role,
        "is_approved": current_user.is_approved if current_user.is_approved is not None else True,
        "created_at": current_user.created_at,
    }


@router.get("/stats")
def get_system_stats(db: Session = Depends(get_db)):
    from ..models import Detection
    total_users = db.query(User).count()
    total_fire_incidents = db.query(Detection).filter(Detection.fire_level > 0).count()
    return {
        "total_users": total_users,
        "total_fire_incidents": total_fire_incidents,
    }


# ── Admin-only user management endpoints ─────────────────────────────────────

@router.get("/users")
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "is_admin": u.is_admin or (get_user_role(u) == "admin"),
            "role": get_user_role(u),
            "is_approved": u.is_approved if u.is_approved is not None else True,
            "created_at": u.created_at,
        }
        for u in users
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    req: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Determine role
    target_role = (body.role or "operator").lower()
    if target_role not in ["admin", "operator", "viewer"]:
        target_role = "admin" if body.is_admin else "operator"
    
    is_admin = (target_role == "admin") or (body.is_admin is True)

    new_user = User(
        username=body.username,
        hashed_password=get_password_hash(body.password),
        is_admin=is_admin,
        role=target_role,
        is_approved=True if body.is_approved is None else body.is_approved,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    client_ip = req.client.host if req.client else None
    log_audit(
        db,
        username=admin.username,
        action="USER_CREATED",
        details=f"Created user '{new_user.username}' with role '{target_role}'",
        user_id=admin.id,
        ip_address=client_ip
    )

    return {
        "id": new_user.id,
        "username": new_user.username,
        "is_admin": new_user.is_admin,
        "role": target_role,
        "is_approved": new_user.is_approved,
        "created_at": new_user.created_at
    }


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdate,
    req: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    old_role = get_user_role(user)
    target_role = old_role

    if body.role is not None:
        target_role = body.role.lower()
        if target_role in ["admin", "operator", "viewer"]:
            user.role = target_role
            user.is_admin = (target_role == "admin")
    elif body.is_admin is not None:
        user.is_admin = body.is_admin
        user.role = "admin" if body.is_admin else "operator"
        target_role = user.role

    if body.is_approved is not None:
        user.is_approved = body.is_approved

    db.commit()
    db.refresh(user)

    client_ip = req.client.host if req.client else None
    log_audit(
        db,
        username=admin.username,
        action="USER_UPDATED",
        details=f"Updated user '{user.username}' (role='{target_role}', approved={user.is_approved})",
        user_id=admin.id,
        ip_address=client_ip
    )

    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "role": get_user_role(user),
        "is_approved": user.is_approved,
        "created_at": user.created_at
    }


@router.post("/users/{user_id}/approve")
def approve_user(
    user_id: int,
    req: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.is_approved = True
    db.commit()
    db.refresh(user)

    client_ip = req.client.host if req.client else None
    log_audit(
        db,
        username=admin.username,
        action="USER_APPROVED",
        details=f"Approved user account '{user.username}' with role '{get_user_role(user)}'",
        user_id=admin.id,
        ip_address=client_ip
    )

    return {"message": f"User '{user.username}' approved successfully", "is_approved": True, "role": get_user_role(user)}


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    body: PasswordResetRequest,
    req: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    user.hashed_password = get_password_hash(body.new_password)
    db.commit()

    client_ip = req.client.host if req.client else None
    log_audit(
        db,
        username=admin.username,
        action="PASSWORD_RESET",
        details=f"Reset password for user '{user.username}'",
        user_id=admin.id,
        ip_address=client_ip
    )

    return {"message": f"Password reset successfully for {user.username}"}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    req: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    deleted_username = user.username
    db.delete(user)
    db.commit()

    client_ip = req.client.host if req.client else None
    log_audit(
        db,
        username=admin.username,
        action="USER_DELETED",
        details=f"Deleted user '{deleted_username}'",
        user_id=admin.id,
        ip_address=client_ip
    )


# ── Audit Trail Endpoints ─────────────────────────────────────────────────────

@router.get("/audit-logs")
def get_audit_logs(
    limit: int = 100,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return [
        {
            "id": log.id,
            "timestamp": log.timestamp,
            "username": log.username,
            "action": log.action,
            "details": log.details,
            "ip_address": log.ip_address
        }
        for log in logs
    ]
