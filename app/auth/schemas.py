from sqlmodel import SQLModel


class UserCreate(SQLModel):
    username: str
    password: str
    invite_code: str


class UserLogin(SQLModel):
    username: str
    password: str


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"
