from fastapi import APIRouter

from app.agent_profiles.schemas import AgentProfileResponse

router = APIRouter(prefix="/api/agent-profiles", tags=["agent-profiles"])


@router.get("", response_model=list[AgentProfileResponse])
def list_agent_profiles():
    return [
        AgentProfileResponse(
            id="hermes-acp",
            name="Hermes ACP",
            runtime="hermes-acp",
            description="Autonomous Hermes runtime executed by agentsdk.",
        )
    ]
