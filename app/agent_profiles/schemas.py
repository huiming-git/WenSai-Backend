from sqlmodel import SQLModel


class AgentProfileResponse(SQLModel):
    id: str
    name: str
    runtime: str
    description: str | None = None
