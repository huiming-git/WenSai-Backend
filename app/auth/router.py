from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.limiter import limiter
from app.auth.schemas import Token, UserCreate, UserLogin
from app.users.models import CreditRedeemCode, User
from app.users.schemas import CreditBalanceResponse, RedeemCodeRequest, RedeemCodeResponse, UserResponse
from app.config import INVITE_CODE
from app.utils import create_access_token, hash_password, verify_password
from app.workspaces.service import create_workspace_for_user, ensure_active_workspace

router = APIRouter(prefix="/api/auth", tags=["auth"])

TEST_CREDIT_USERNAME = "huiming"
TEST_CREDIT_BONUS = 1000


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, user_in: UserCreate, db: Session = Depends(get_db)):
    # Verify invite code
    if user_in.invite_code != INVITE_CODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid invite code",
        )

    # Check if username already exists
    existing = db.query(User).filter(User.username == user_in.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    user = User(
        username=user_in.username,
        hashed_password=hash_password(user_in.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    workspace = create_workspace_for_user(db, user, "个人空间")
    user.active_workspace_id = workspace.id
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(request: Request, user_in: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == user_in.username).first()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
def get_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_active_workspace(db, current_user)
    db.refresh(current_user)
    return current_user


@router.get("/credits", response_model=CreditBalanceResponse)
def get_credits(current_user: User = Depends(get_current_user)):
    return CreditBalanceResponse(credits=current_user.credits)


@router.post("/redeem-code", response_model=RedeemCodeResponse)
def redeem_code(
    redeem_in: RedeemCodeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    raw_code = redeem_in.code.strip()
    if not raw_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Redeem code is required")

    normalized_code = raw_code.upper()
    if current_user.username == TEST_CREDIT_USERNAME:
        current_user.credits += TEST_CREDIT_BONUS
        db.add(current_user)
        db.commit()
        db.refresh(current_user)
        return RedeemCodeResponse(
            credits=current_user.credits,
            added=TEST_CREDIT_BONUS,
            code=normalized_code,
            message="测试账号已增加 1000 积分",
        )

    redeem_code_record = (
        db.query(CreditRedeemCode)
        .filter(CreditRedeemCode.code == normalized_code)
        .first()
    )
    if not redeem_code_record or redeem_code_record.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or used redeem code")

    current_user.credits += redeem_code_record.credits
    redeem_code_record.status = "used"
    redeem_code_record.used_by = current_user.id
    redeem_code_record.used_at = datetime.utcnow()

    db.add(current_user)
    db.add(redeem_code_record)
    db.commit()
    db.refresh(current_user)

    return RedeemCodeResponse(
        credits=current_user.credits,
        added=redeem_code_record.credits,
        code=normalized_code,
        message="积分兑换成功",
    )
