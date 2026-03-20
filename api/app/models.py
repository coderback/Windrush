from pydantic import BaseModel
from typing import Any


class SkillRisk(BaseModel):
    skill: str
    onet_code: str | None = None
    occupation_name: str = ""
    overall_exposure: float = 0.5


class CVProfile(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    skills: list[str] = []
    experience_years: float = 0
    job_titles: list[str] = []
    summary: str = ""


class JobMatch(BaseModel):
    job_id: str
    title: str
    company: str
    location: str
    description: str = ""
    url: str = ""
    fit_score: float = 0.0
    exposure_score: float = 0.5
    composite_score: float = 0.0


class RoadmapItem(BaseModel):
    skill: str
    action: str
    timeline: str
    resource: str = ""


class AgentEvent(BaseModel):
    type: str
    timestamp: float
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    result: Any | None = None
    text: str | None = None
