"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { authFetch } from "../api";

interface WorkExperience {
  employer: string;
  title: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  tech_stack: string[];
  achievements: string[];
  metrics: string;
  summary: string;
}

interface Education {
  institution: string;
  degree: string;
  start_date: string;
  end_date: string;
  grade: string;
  is_currently_enrolled: boolean;
}

interface Project {
  name: string;
  url?: string;
  problem_solved: string;
  technologies: string[];
  outcomes: string;
  summary: string;
  is_ongoing: boolean;
}

interface Certification {
  name: string;
  issuing_organization: string;
  issue_date: string;
  expiration_date: string;
  credential_id: string;
  credential_url: string;
}

interface BehavioralStory {
  title: string;
  scenario: string;
  action: string;
  result: string;
  tags: string[];
}

interface SkillCategory {
  category: string;
  skills: string[];
}

interface Persona {
  core_info: {
    first_name: string;
    last_name: string;
    preferred_name: string;
    dob: string;
    email: string;
    phone: string;
    address_line_1: string;
    city: string;
    country: string;
    postcode: string;
    linkedin: string;
    github: string;
    twitter: string;
    portfolio: string;
    website: string;
    visa_status: string;
    visa_type: string;
    right_to_work_uk: boolean;
    require_sponsorship: boolean;
    security_clearance: string;
    has_government_ties: boolean;
    job_email: string;
    job_password: string;
  };
  diversity: {
    gender: string;
    ethnicity: string;
    disability_status: string;
    veteran_status: string;
    sexual_orientation: string;
  };
  screening: {
    why_this_role: string;
    why_this_company: string;
    greatest_strength: string;
    biggest_weakness: string;
    leadership_example: string;
    conflict_resolution: string;
    salary_canonical: string;
    notice_period_canonical: string;
  };
  preferences: {
    target_titles: string[];
    min_salary?: number;
    expected_hourly_rate?: number;
    remote_preference: string;
    relocation_willingness: boolean;
    preferred_locations: string[];
    industries: string[];
    companies_to_avoid: string[];
    company_size_preference: string;
    employment_type: string;
    notice_period: string;
    can_work_in_person: boolean;
    can_start_immediately: boolean;
    has_reliable_transportation: boolean;
    needs_accommodations: boolean;
  };
  history: WorkExperience[];
  education: Education[];
  projects: Project[];
  certifications: Certification[];
  story_bank: BehavioralStory[];
  custom_directives: string;
  skills: SkillCategory[];
  summary: string;
}

const SECTIONS = [
  "Core Info",
  "Application Credentials",
  "Social & Links",
  "Skills",
  "Certifications",
  "Education",
  "Experience",
  "Projects",
  "Story Bank",
  "Screening Vault",
  "Diversity & Compliance",
  "Preferences",
  "Directives"
];

export default function ProfilePage() {
  const router = useRouter();
  const [activeSection, setActiveSection] = useState("Core Info");
  const [persona, setPersona] = useState<Persona | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchPersona = async () => {
      try {
        const res = await authFetch("/api/persona");
        if (res.ok) {
          const data = await res.json();
          setPersona(data);
        }
      } catch (err) {
        setError("Failed to load profile");
      } finally {
        setLoading(false);
      }
    };
    fetchPersona();
  }, []);

  const savePersona = async (updated: Persona) => {
    setSaving(true);
    setError(null);
    try {
      const res = await authFetch("/api/persona", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated),
      });
      if (!res.ok) throw new Error("Failed to save");
    } catch (err) {
      setError("Error saving changes");
    } finally {
      setSaving(false);
    }
  };

  const handleChange = (section: keyof Persona, field: string, value: any) => {
    if (!persona) return;
    setPersona(prev => {
      if (!prev) return null;
      const updated = { ...prev };
      if (["core_info", "preferences", "diversity", "screening"].includes(section)) {
        updated[section] = { ...(prev[section] as any), [field]: value };
      } else {
        (updated as any)[section] = value;
      }
      return updated as Persona;
    });
  };

  if (loading) return <div className="p-10 text-zinc-500">Loading Digital Twin...</div>;
  if (!persona) return <div className="p-10 text-red-500">Error loading Twin</div>;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-mono">
      <header className="border-b border-zinc-800 px-6 py-4 flex items-center justify-between sticky top-0 bg-zinc-950/80 backdrop-blur-md z-20">
        <div className="flex items-center gap-4">
          <button onClick={() => router.push("/")} className="text-zinc-500 hover:text-zinc-300">←</button>
          <h1 className="text-xl font-bold" style={{ fontFamily: "Playfair Display, serif" }}>Digital Twin Persona</h1>
        </div>
        <div className="flex items-center gap-4">
          {saving && <span className="text-xs text-teal-400 animate-pulse">Syncing...</span>}
          {error && <span className="text-xs text-red-500">{error}</span>}
          <button 
            onClick={() => savePersona(persona)}
            disabled={saving}
            className="px-4 py-1.5 bg-white text-black text-sm font-bold rounded-lg hover:bg-zinc-200 transition-colors disabled:opacity-50"
          >
            Save Persona
          </button>
        </div>
      </header>

      <div className="max-w-7xl mx-auto flex gap-8 p-8">
        <aside className="w-64 space-y-1 shrink-0">
          {SECTIONS.map((s) => (
            <button
              key={s}
              onClick={() => setActiveSection(s)}
              className={`w-full text-left px-4 py-2 rounded-lg text-sm transition-colors ${
                activeSection === s ? "bg-zinc-800 text-teal-400 font-bold" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {s}
            </button>
          ))}
        </aside>

        <main className="flex-1 bg-zinc-900/30 border border-zinc-800 rounded-2xl p-8 space-y-8 min-h-[700px]">
          
          {activeSection === "Core Info" && (
            <div className="space-y-6">
              <h2 className="text-lg font-bold border-b border-zinc-800 pb-2">Identity & Contact</h2>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">First Name</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.first_name} onChange={(e) => handleChange("core_info", "first_name", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Last Name</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.last_name} onChange={(e) => handleChange("core_info", "last_name", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Preferred Name</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.preferred_name} onChange={(e) => handleChange("core_info", "preferred_name", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Date of Birth</label>
                  <input type="date" className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.dob} onChange={(e) => handleChange("core_info", "dob", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Address Line 1</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.address_line_1} onChange={(e) => handleChange("core_info", "address_line_1", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">City</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.city} onChange={(e) => handleChange("core_info", "city", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Postcode / Zip</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.postcode} onChange={(e) => handleChange("core_info", "postcode", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Country</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.country} onChange={(e) => handleChange("core_info", "country", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Phone Number</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.phone} onChange={(e) => handleChange("core_info", "phone", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Security Clearance</label>
                  <input placeholder="None, SC, DV, etc." className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.security_clearance} onChange={(e) => handleChange("core_info", "security_clearance", e.target.value)} />
                </div>
              </div>
            </div>
          )}

          {activeSection === "Application Credentials" && (
            <div className="space-y-6">
              <h2 className="text-lg font-bold border-b border-zinc-800 pb-2">Application Credentials</h2>
              <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
                <p className="text-xs text-amber-400">
                  Stored in your profile and used to auto-fill login forms during browser-based apply. Never shared externally.
                </p>
              </div>
              <div className="grid grid-cols-1 gap-4 max-w-md">
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Job-board email</label>
                  <input
                    type="email"
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none"
                    value={persona.core_info.job_email ?? ""}
                    onChange={(e) => handleChange("core_info", "job_email", e.target.value)}
                    placeholder="you@example.com"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Master password</label>
                  <input
                    type="password"
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none"
                    value={persona.core_info.job_password ?? ""}
                    onChange={(e) => handleChange("core_info", "job_password", e.target.value)}
                    placeholder="••••••••"
                  />
                </div>
              </div>
            </div>
          )}

          {activeSection === "Social & Links" && (
            <div className="space-y-6">
              <h2 className="text-lg font-bold border-b border-zinc-800 pb-2">Professional Links</h2>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">LinkedIn URL</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.linkedin} onChange={(e) => handleChange("core_info", "linkedin", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">GitHub URL</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.github} onChange={(e) => handleChange("core_info", "github", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Portfolio</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.portfolio} onChange={(e) => handleChange("core_info", "portfolio", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Twitter/X</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.twitter} onChange={(e) => handleChange("core_info", "twitter", e.target.value)} />
                </div>
              </div>
            </div>
          )}

          {activeSection === "Skills" && (
            <div className="space-y-6">
               <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                 <h2 className="text-lg font-bold">Categorized Skills</h2>
                 <button onClick={() => handleChange("skills", "skills", [...persona.skills, {category: "", skills: []}])} className="text-xs text-teal-400 hover:underline">+ Add Category</button>
               </div>
               <p className="text-xs text-zinc-500 italic">The agent uses these categories to answer technical forms precisely.</p>
               {persona.skills.map((cat, i) => (
                 <div key={i} className="p-4 bg-zinc-950/50 border border-zinc-800 rounded-lg space-y-3">
                   <div className="flex gap-4 items-center">
                     <input placeholder="Category (e.g. Languages)" className="flex-1 bg-transparent border-b border-zinc-800 p-1 text-sm font-bold outline-none" value={cat.category} onChange={(e) => { const arr = [...persona.skills]; arr[i].category = e.target.value; handleChange("skills", "skills", arr); }}/>
                     <button onClick={() => { const arr = [...persona.skills]; arr.splice(i, 1); handleChange("skills", "skills", arr); }} className="text-xs text-red-900 hover:text-red-500 transition-colors">Delete</button>
                   </div>
                   <input placeholder="Skills (comma separated, e.g. Python, Go, Java)" className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={cat.skills.join(", ")} onChange={(e) => { const arr = [...persona.skills]; arr[i].skills = e.target.value.split(",").map(s => s.trim()).filter(Boolean); handleChange("skills", "skills", arr); }} />
                 </div>
               ))}
            </div>
          )}

          {activeSection === "Certifications" && (
            <div className="space-y-6">
              <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                <h2 className="text-lg font-bold">Certifications</h2>
                <button onClick={() => handleChange("certifications", "certifications", [...persona.certifications, {name: "", issuing_organization: "", issue_date: "", expiration_date: "", credential_id: "", credential_url: ""}])} className="text-xs text-teal-400 hover:underline">+ Add Certification</button>
              </div>
              {persona.certifications.map((cert, i) => (
                <div key={i} className="p-4 bg-zinc-950/50 border border-zinc-800 rounded-lg space-y-3">
                   <div className="grid grid-cols-2 gap-4">
                     <input placeholder="Certification Name" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={cert.name} onChange={(e) => { const arr = [...persona.certifications]; arr[i].name = e.target.value; handleChange("certifications", "certifications", arr); }}/>
                     <input placeholder="Issuing Organization" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={cert.issuing_organization} onChange={(e) => { const arr = [...persona.certifications]; arr[i].issuing_organization = e.target.value; handleChange("certifications", "certifications", arr); }}/>
                   </div>
                   <div className="grid grid-cols-2 gap-4">
                     <div className="space-y-1">
                       <label className="text-[10px] text-zinc-500 uppercase">Issue Date</label>
                       <input type="month" className="w-full bg-zinc-950 border border-zinc-800 rounded p-1 text-xs outline-none" value={cert.issue_date} onChange={(e) => { const arr = [...persona.certifications]; arr[i].issue_date = e.target.value; handleChange("certifications", "certifications", arr); }}/>
                     </div>
                     <div className="space-y-1">
                       <label className="text-[10px] text-zinc-500 uppercase">Expiry Date</label>
                       <input type="month" className="w-full bg-zinc-950 border border-zinc-800 rounded p-1 text-xs outline-none" value={cert.expiration_date} onChange={(e) => { const arr = [...persona.certifications]; arr[i].expiration_date = e.target.value; handleChange("certifications", "certifications", arr); }}/>
                     </div>
                   </div>
                </div>
              ))}
            </div>
          )}

          {activeSection === "Education" && (
            <div className="space-y-6">
              <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                <h2 className="text-lg font-bold">Education</h2>
                <button 
                  onClick={() => handleChange("education", "education", [...persona.education, {institution: "", degree: "", start_date: "", end_date: "", grade: "", is_currently_enrolled: false}])}
                  className="text-xs text-teal-400 hover:underline"
                >+ Add Education</button>
              </div>
              {persona.education.map((edu, i) => (
                <div key={i} className="p-4 bg-zinc-950/50 border border-zinc-800 rounded-lg space-y-3">
                   <div className="grid grid-cols-2 gap-4">
                     <input placeholder="Institution" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={edu.institution} onChange={(e) => {
                       const arr = [...persona.education]; arr[i].institution = e.target.value; handleChange("education", "education", arr);
                     }}/>
                     <input placeholder="Degree" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={edu.degree} onChange={(e) => {
                       const arr = [...persona.education]; arr[i].degree = e.target.value; handleChange("education", "education", arr);
                     }}/>
                   </div>
                   <div className="grid grid-cols-4 gap-4 items-center">
                     <input type="month" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={edu.start_date} onChange={(e) => {
                       const arr = [...persona.education]; arr[i].start_date = e.target.value; handleChange("education", "education", arr);
                     }}/>
                     <input type="month" disabled={edu.is_currently_enrolled} className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none disabled:opacity-30" value={edu.end_date} onChange={(e) => {
                       const arr = [...persona.education]; arr[i].end_date = e.target.value; handleChange("education", "education", arr);
                     }}/>
                     <input placeholder="Grade (e.g. 2:1)" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={edu.grade} onChange={(e) => {
                       const arr = [...persona.education]; arr[i].grade = e.target.value; handleChange("education", "education", arr);
                     }}/>
                     <label className="flex items-center gap-2 text-xs text-zinc-500">
                        <input type="checkbox" checked={edu.is_currently_enrolled} onChange={(e) => { const arr = [...persona.education]; arr[i].is_currently_enrolled = e.target.checked; if(e.target.checked) arr[i].end_date = ""; handleChange("education", "education", arr); }} />
                        Currently enrolled
                     </label>
                   </div>
                </div>
              ))}
            </div>
          )}

          {activeSection === "Experience" && (
            <div className="space-y-6">
               <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                 <h2 className="text-lg font-bold">Work History</h2>
                 <button onClick={() => handleChange("history", "history", [...persona.history, {employer: "", title: "", start_date: "", end_date: "", is_current: false, summary: "", achievements: [], metrics: "", tech_stack: []}])} className="text-xs text-teal-400 hover:underline">+ Add Role</button>
               </div>
               {persona.history.map((exp, i) => (
                 <div key={i} className="p-4 bg-zinc-950/50 border border-zinc-800 rounded-lg space-y-3">
                   <div className="grid grid-cols-2 gap-4">
                     <input placeholder="Employer" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={exp.employer} onChange={(e) => { const h = [...persona.history]; h[i].employer = e.target.value; handleChange("history", "history", h); }}/>
                     <input placeholder="Job Title" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={exp.title} onChange={(e) => { const h = [...persona.history]; h[i].title = e.target.value; handleChange("history", "history", h); }}/>
                   </div>
                   <div className="grid grid-cols-3 gap-4 items-center">
                     <input type="month" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={exp.start_date} onChange={(e) => { const h = [...persona.history]; h[i].start_date = e.target.value; handleChange("history", "history", h); }}/>
                     <input type="month" disabled={exp.is_current} className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none disabled:opacity-30" value={exp.end_date} onChange={(e) => { const h = [...persona.history]; h[i].end_date = e.target.value; handleChange("history", "history", h); }}/>
                     <label className="flex items-center gap-2 text-xs text-zinc-500">
                        <input type="checkbox" checked={exp.is_current} onChange={(e) => { const h = [...persona.history]; h[i].is_current = e.target.checked; if(e.target.checked) h[i].end_date = ""; handleChange("history", "history", h); }} />
                        I currently work here
                     </label>
                   </div>
                   <textarea placeholder="Achievements & Metrics (e.g. Led team of 5, increased velocity by 30%)" className="w-full bg-transparent border border-zinc-800 rounded p-2 text-sm h-20 outline-none" value={exp.metrics} onChange={(e) => { const h = [...persona.history]; h[i].metrics = e.target.value; handleChange("history", "history", h); }} />
                 </div>
               ))}
            </div>
          )}

          {activeSection === "Projects" && (
            <div className="space-y-6">
              <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                <h2 className="text-lg font-bold">Key Projects</h2>
                <button onClick={() => handleChange("projects", "projects", [...persona.projects, {name: "", problem_solved: "", technologies: [], outcomes: "", summary: "", url: "", is_ongoing: false}])} className="text-xs text-teal-400 hover:underline">+ Add Project</button>
              </div>
              {persona.projects.map((proj, i) => (
                <div key={i} className="p-4 bg-zinc-950/50 border border-zinc-800 rounded-lg space-y-3">
                   <div className="grid grid-cols-2 gap-4">
                     <input placeholder="Project Name" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={proj.name} onChange={(e) => { const p = [...persona.projects]; p[i].name = e.target.value; handleChange("projects", "projects", p); }}/>
                     <input placeholder="URL" className="bg-transparent border-b border-zinc-800 p-1 text-sm outline-none" value={proj.url} onChange={(e) => { const p = [...persona.projects]; p[i].url = e.target.value; handleChange("projects", "projects", p); }}/>
                   </div>
                   <textarea placeholder="What problem did you solve?" className="w-full bg-transparent border border-zinc-800 rounded p-2 text-sm h-20 outline-none" value={proj.problem_solved} onChange={(e) => { const p = [...persona.projects]; p[i].problem_solved = e.target.value; handleChange("projects", "projects", p); }} />
                   <textarea placeholder="Outcomes & Technologies" className="w-full bg-transparent border border-zinc-800 rounded p-2 text-sm h-20 outline-none" value={proj.outcomes} onChange={(e) => { const p = [...persona.projects]; p[i].outcomes = e.target.value; handleChange("projects", "projects", p); }} />
                   <label className="flex items-center gap-2 text-xs text-zinc-500">
                      <input type="checkbox" checked={proj.is_ongoing} onChange={(e) => { const p = [...persona.projects]; p[i].is_ongoing = e.target.checked; handleChange("projects", "projects", p); }} />
                      Ongoing project
                   </label>
                </div>
              ))}
            </div>
          )}

          {activeSection === "Story Bank" && (
            <div className="space-y-6">
               <h2 className="text-lg font-bold border-b border-zinc-800 pb-2">Behavioral Stories (STAR Method)</h2>
               <div className="p-3 bg-teal-500/10 border border-teal-500/20 rounded-lg">
                 <p className="text-xs text-teal-400 font-bold uppercase tracking-widest mb-1">STAR Framework Reminder:</p>
                 <p className="text-xs text-zinc-400 italic">S: Situation | T: Task | A: Action | R: Result (Focus on the Impact!)</p>
               </div>
               <button 
                   onClick={() => handleChange("story_bank", "story_bank", [...persona.story_bank, {title: "", scenario: "", action: "", result: "", tags: []}])}
                   className="text-xs text-teal-400 hover:underline"
                 >+ Add Story</button>
               {persona.story_bank.map((story, i) => (
                 <div key={i} className="p-4 bg-zinc-950/50 border border-zinc-800 rounded-lg space-y-3">
                    <input placeholder="Story Title (e.g. Scaling the API)" className="w-full bg-transparent border-b border-zinc-800 p-1 text-sm font-bold outline-none" value={story.title} onChange={(e) => {
                       const s = [...persona.story_bank]; s[i].title = e.target.value; handleChange("story_bank", "story_bank", s);
                    }}/>
                    <div className="grid grid-cols-1 gap-2">
                       <textarea placeholder="Situation/Task (The Context)" className="bg-transparent border border-zinc-800 rounded p-2 text-xs h-16 outline-none" value={story.scenario} onChange={(e) => {
                         const s = [...persona.story_bank]; s[i].scenario = e.target.value; handleChange("story_bank", "story_bank", s);
                       }}/>
                       <textarea placeholder="Action Taken (What YOU did)" className="bg-transparent border border-zinc-800 rounded p-2 text-xs h-16 outline-none" value={story.action} onChange={(e) => {
                         const s = [...persona.story_bank]; s[i].action = e.target.value; handleChange("story_bank", "story_bank", s);
                       }}/>
                       <textarea placeholder="Result (The quantified outcome)" className="bg-transparent border border-zinc-800 rounded p-2 text-xs h-16 outline-none" value={story.result} onChange={(e) => {
                         const s = [...persona.story_bank]; s[i].result = e.target.value; handleChange("story_bank", "story_bank", s);
                       }}/>
                    </div>
                 </div>
               ))}
            </div>
          )}

          {activeSection === "Screening Vault" && (
            <div className="space-y-6">
              <h2 className="text-lg font-bold border-b border-zinc-800 pb-2">Common Screening Answers</h2>
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Why this role?</label>
                  <textarea className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm h-24 focus:border-teal-500 outline-none" value={persona.screening.why_this_role} onChange={(e) => handleChange("screening", "why_this_role", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Why this company?</label>
                  <textarea className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm h-24 focus:border-teal-500 outline-none" value={persona.screening.why_this_company} onChange={(e) => handleChange("screening", "why_this_company", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Greatest Strength</label>
                  <textarea className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm h-20 focus:border-teal-500 outline-none" value={persona.screening.greatest_strength} onChange={(e) => handleChange("screening", "greatest_strength", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Biggest Weakness</label>
                  <textarea className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm h-20 focus:border-teal-500 outline-none" value={persona.screening.biggest_weakness} onChange={(e) => handleChange("screening", "biggest_weakness", e.target.value)} />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <label className="text-xs text-zinc-500 uppercase">Notice Period</label>
                    <input placeholder="e.g. 1 month, Immediate" className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.screening.notice_period_canonical} onChange={(e) => handleChange("screening", "notice_period_canonical", e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs text-zinc-500 uppercase">Salary Expectations (Canonical)</label>
                    <input placeholder="e.g. £50k, Competitive" className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.screening.salary_canonical} onChange={(e) => handleChange("screening", "salary_canonical", e.target.value)} />
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeSection === "Diversity & Compliance" && (
            <div className="space-y-6">
              <h2 className="text-lg font-bold border-b border-zinc-800 pb-2">Diversity & Inclusion (Optional)</h2>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Gender</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.diversity.gender} onChange={(e) => handleChange("diversity", "gender", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Ethnicity</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.diversity.ethnicity} onChange={(e) => handleChange("diversity", "ethnicity", e.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Disability Status</label>
                  <select className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.diversity.disability_status} onChange={(e) => handleChange("diversity", "disability_status", e.target.value)}>
                    <option value="">Select...</option>
                    <option value="yes">Yes, I have a disability</option>
                    <option value="no">No, I do not</option>
                    <option value="prefer_not_to_say">Prefer not to say</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Veteran Status</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.diversity.veteran_status} onChange={(e) => handleChange("diversity", "veteran_status", e.target.value)} />
                </div>
                <div className="space-y-2 flex items-center justify-between bg-zinc-950/50 p-4 rounded-lg border border-zinc-800">
                  <span className="text-sm">Has Government Ties</span>
                  <input type="checkbox" checked={persona.core_info.has_government_ties} onChange={(e) => handleChange("core_info", "has_government_ties", e.target.checked)} className="accent-teal-500" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Visa Type</label>
                  <input placeholder="H1-B, Skilled Worker, etc." className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.core_info.visa_type} onChange={(e) => handleChange("core_info", "visa_type", e.target.value)} />
                </div>
              </div>
            </div>
          )}

          {activeSection === "Preferences" && (
            <div className="space-y-6">
              <h2 className="text-lg font-bold border-b border-zinc-800 pb-2">Job Preferences</h2>
              <div className="grid grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Minimum Salary (Annual)</label>
                  <input type="number" className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.preferences.min_salary || ""} onChange={(e) => handleChange("preferences", "min_salary", parseInt(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Hourly Rate (Expected)</label>
                  <input type="number" className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.preferences.expected_hourly_rate || ""} onChange={(e) => handleChange("preferences", "expected_hourly_rate", parseFloat(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Work Setting</label>
                  <select className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.preferences.remote_preference} onChange={(e) => handleChange("preferences", "remote_preference", e.target.value)}>
                    <option value="remote">Remote-only</option>
                    <option value="hybrid">Hybrid</option>
                    <option value="onsite">On-site</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-zinc-500 uppercase">Employment Type</label>
                  <select className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={persona.preferences.employment_type} onChange={(e) => handleChange("preferences", "employment_type", e.target.value)}>
                    <option value="full-time">Full-time</option>
                    <option value="contract">Contract</option>
                    <option value="internship">Internship</option>
                  </select>
                </div>
                <div className="space-y-2 col-span-2">
                  <label className="text-xs text-zinc-500 uppercase">Preferred Locations (comma separated)</label>
                  <input className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-sm focus:border-teal-500 outline-none" value={(persona.preferences.preferred_locations || []).join(", ")} onChange={(e) => handleChange("preferences", "preferred_locations", e.target.value.split(",").map(s => s.trim()))} placeholder="e.g. London, Manchester, New York" />
                </div>
              </div>
              
              <div className="grid grid-cols-2 gap-4 pt-4 border-t border-zinc-800">
                <div className="flex items-center justify-between bg-zinc-950/50 p-4 rounded-lg border border-zinc-800">
                  <span className="text-sm">Willing to Relocate</span>
                  <input type="checkbox" checked={persona.preferences.relocation_willingness} onChange={(e) => handleChange("preferences", "relocation_willingness", e.target.checked)} className="accent-teal-500" />
                </div>
                <div className="flex items-center justify-between bg-zinc-950/50 p-4 rounded-lg border border-zinc-800">
                  <span className="text-sm">Can start immediately</span>
                  <input type="checkbox" checked={persona.preferences.can_start_immediately} onChange={(e) => handleChange("preferences", "can_start_immediately", e.target.checked)} className="accent-teal-500" />
                </div>
                <div className="flex items-center justify-between bg-zinc-950/50 p-4 rounded-lg border border-zinc-800">
                  <span className="text-sm">Has reliable transportation</span>
                  <input type="checkbox" checked={persona.preferences.has_reliable_transportation} onChange={(e) => handleChange("preferences", "has_reliable_transportation", e.target.checked)} className="accent-teal-500" />
                </div>
                <div className="flex items-center justify-between bg-zinc-950/50 p-4 rounded-lg border border-zinc-800">
                  <span className="text-sm">Needs accommodations</span>
                  <input type="checkbox" checked={persona.preferences.needs_accommodations} onChange={(e) => handleChange("preferences", "needs_accommodations", e.target.checked)} className="accent-teal-500" />
                </div>
              </div>
            </div>
          )}

          {activeSection === "Directives" && (
            <div className="space-y-6">
              <h2 className="text-lg font-bold border-b border-zinc-800 pb-2">Custom AI Directives</h2>
              <p className="text-xs text-zinc-500">Specific instructions for how the AI should write your cover letters and interact with recruiters.</p>
              <textarea 
                placeholder="e.g. 'Always emphasize my passion for open source. Use a very professional and slightly academic tone...'"
                className="w-full bg-zinc-950 border border-zinc-800 rounded p-4 text-sm h-64 outline-none focus:border-teal-500 transition-colors"
                value={persona.custom_directives}
                onChange={(e) => handleChange("custom_directives", "custom_directives", e.target.value)}
              />
            </div>
          )}

        </main>
      </div>
    </div>
  );
}
