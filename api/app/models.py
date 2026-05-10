from pydantic import BaseModel, Field
from typing import Any, List, Optional


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


# ── PERSONA MODELS ────────────────────────────────────────────────────────────

class WorkExperience(BaseModel):
    employer: str
    title: str
    start_date: str = ""
    end_date: str = ""
    is_current: bool = False
    tech_stack: List[str] = []
    achievements: List[str] = []
    metrics: str = "" # e.g. "Increased revenue by 20%"
    summary: str = ""

class Education(BaseModel):
    institution: str
    degree: str
    start_date: str = ""
    end_date: str = ""
    grade: str = "" # e.g. "First Class Honours" or "3.8 GPA"
    is_currently_enrolled: bool = False

class Project(BaseModel):
    name: str
    url: Optional[str] = None
    problem_solved: str = ""
    technologies: List[str] = []
    outcomes: str = ""
    summary: str = ""
    is_ongoing: bool = False

class BehavioralStory(BaseModel):
    title: str
    scenario: str
    action: str
    result: str
    tags: List[str] = []

class SkillCategory(BaseModel):
    category: str
    skills: List[str] = []

class Certification(BaseModel):
    name: str
    issuing_organization: str
    issue_date: str = ""
    expiration_date: str = ""
    credential_id: str = ""
    credential_url: str = ""

class DiversityInfo(BaseModel):
    gender: str = ""
    ethnicity: str = ""
    disability_status: str = "" # "yes", "no", "prefer_not_to_say"
    veteran_status: str = ""
    sexual_orientation: str = ""

class ScreeningVault(BaseModel):
    why_this_role: str = ""
    why_this_company: str = ""
    greatest_strength: str = ""
    biggest_weakness: str = ""
    leadership_example: str = ""
    conflict_resolution: str = ""
    salary_canonical: str = ""
    notice_period_canonical: str = ""

class CoreInfo(BaseModel):
    first_name: str = ""
    last_name: str = ""
    preferred_name: str = ""
    dob: str = "" # Date of Birth
    email: str = ""
    phone: str = ""
    address_line_1: str = ""
    city: str = ""
    country: str = ""
    postcode: str = ""
    linkedin: str = ""
    github: str = ""
    twitter: str = ""
    portfolio: str = ""
    website: str = ""
    visa_status: str = ""
    visa_type: str = ""
    right_to_work_uk: bool = True
    require_sponsorship: bool = False
    security_clearance: str = ""
    has_government_ties: bool = False
    job_email: str = ""
    job_password: str = ""

class JobPreferences(BaseModel):
    target_titles: List[str] = []
    min_salary: Optional[int] = None
    expected_hourly_rate: Optional[float] = None
    remote_preference: str = "remote"
    relocation_willingness: bool = False
    preferred_locations: List[str] = []
    industries: List[str] = []
    companies_to_avoid: List[str] = []
    company_size_preference: str = "" # e.g. "Startup", "Scale-up", "Enterprise"
    employment_type: str = "full-time" # "full-time", "contract", "internship"
    notice_period: str = ""
    can_work_in_person: bool = True
    can_start_immediately: bool = False
    has_reliable_transportation: bool = True
    needs_accommodations: bool = False

class Persona(BaseModel):
    core_info: CoreInfo = Field(default_factory=CoreInfo)
    preferences: JobPreferences = Field(default_factory=JobPreferences)
    diversity: DiversityInfo = Field(default_factory=DiversityInfo)
    screening: ScreeningVault = Field(default_factory=ScreeningVault)
    history: List[WorkExperience] = []
    education: List[Education] = []
    projects: List[Project] = []
    certifications: List[Certification] = []
    story_bank: List[BehavioralStory] = []
    custom_directives: str = ""
    skills: List[SkillCategory] = []
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
    level_match: str = "ok"
    skill_gaps: list[str] = []


class ApplicationRecord(BaseModel):
    id: str
    job_id: str
    job_title: str
    company: str
    location: str = ""
    job_url: str = ""
    status: str = "Evaluated"
    date_applied: str | None = None
    composite_score: float | None = None
    exposure_score: float | None = None
    fit_score: float | None = None
    skill_gaps: list[str] = []
    level_match: str = "ok"
    notes: str = ""
    created_at: str


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
