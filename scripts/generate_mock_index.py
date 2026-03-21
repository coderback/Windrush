"""Generate a mock economic_index.json based on known ONET codes and AI exposure patterns."""
import json
from pathlib import Path

# Based on publicly available AI exposure research (Acemoglu, Felten, Webb, etc.)
# Scores represent fraction of tasks automatable by AI (0=safe, 1=high risk)
OCCUPATIONS = {
    # High exposure (AI can do most tasks)
    "15-1251.00": {"occupation_name": "Computer Programmers", "overall_exposure": 0.72},
    "15-1252.00": {"occupation_name": "Software Developers", "overall_exposure": 0.65},
    "15-1299.08": {"occupation_name": "Machine Learning Engineers", "overall_exposure": 0.60},
    "43-3031.00": {"occupation_name": "Bookkeeping Clerks", "overall_exposure": 0.83},
    "43-4051.00": {"occupation_name": "Customer Service Representatives", "overall_exposure": 0.77},
    "43-9041.00": {"occupation_name": "Insurance Claims Clerks", "overall_exposure": 0.80},
    "43-9061.00": {"occupation_name": "Office Clerks, General", "overall_exposure": 0.75},
    "13-2011.00": {"occupation_name": "Accountants and Auditors", "overall_exposure": 0.76},
    "13-2051.00": {"occupation_name": "Financial Analysts", "overall_exposure": 0.70},
    "23-2011.00": {"occupation_name": "Paralegals and Legal Assistants", "overall_exposure": 0.74},
    "27-3042.00": {"occupation_name": "Technical Writers", "overall_exposure": 0.69},
    "27-3091.00": {"occupation_name": "Interpreters and Translators", "overall_exposure": 0.73},
    "15-2041.00": {"occupation_name": "Statisticians", "overall_exposure": 0.62},
    "15-2031.00": {"occupation_name": "Operations Research Analysts", "overall_exposure": 0.64},
    "43-6011.00": {"occupation_name": "Executive Secretaries", "overall_exposure": 0.70},
    "43-6014.00": {"occupation_name": "Secretaries and Administrative Assistants", "overall_exposure": 0.72},

    # Medium-high exposure
    "11-3031.00": {"occupation_name": "Financial Managers", "overall_exposure": 0.55},
    "11-2021.00": {"occupation_name": "Marketing Managers", "overall_exposure": 0.52},
    "13-1161.00": {"occupation_name": "Market Research Analysts", "overall_exposure": 0.58},
    "13-1081.00": {"occupation_name": "Logisticians", "overall_exposure": 0.53},
    "11-3071.00": {"occupation_name": "Transportation Managers", "overall_exposure": 0.50},
    "27-1021.00": {"occupation_name": "Commercial and Industrial Designers", "overall_exposure": 0.48},
    "27-1024.00": {"occupation_name": "Graphic Designers", "overall_exposure": 0.55},
    "27-2041.00": {"occupation_name": "Music Directors and Composers", "overall_exposure": 0.42},
    "15-1211.00": {"occupation_name": "Computer Systems Analysts", "overall_exposure": 0.60},
    "15-1244.00": {"occupation_name": "Network Architects", "overall_exposure": 0.55},
    "13-1111.00": {"occupation_name": "Management Analysts", "overall_exposure": 0.58},
    "13-1071.00": {"occupation_name": "Human Resources Specialists", "overall_exposure": 0.52},

    # Medium exposure
    "11-1021.00": {"occupation_name": "General and Operations Managers", "overall_exposure": 0.43},
    "11-2011.00": {"occupation_name": "Advertising and Promotions Managers", "overall_exposure": 0.48},
    "11-9041.00": {"occupation_name": "Architectural and Engineering Managers", "overall_exposure": 0.38},
    "19-3011.00": {"occupation_name": "Economists", "overall_exposure": 0.45},
    "19-3051.00": {"occupation_name": "Urban and Regional Planners", "overall_exposure": 0.40},
    "11-9121.00": {"occupation_name": "Natural Sciences Managers", "overall_exposure": 0.37},
    "25-1011.00": {"occupation_name": "Business Teachers, Postsecondary", "overall_exposure": 0.42},
    "23-1011.00": {"occupation_name": "Lawyers", "overall_exposure": 0.44},
    "19-4012.00": {"occupation_name": "Agricultural Technicians", "overall_exposure": 0.35},

    # Lower exposure (human skills dominant)
    "11-9031.00": {"occupation_name": "Education Administrators", "overall_exposure": 0.28},
    "21-1021.00": {"occupation_name": "Child, Family, and School Social Workers", "overall_exposure": 0.22},
    "21-1022.00": {"occupation_name": "Healthcare Social Workers", "overall_exposure": 0.20},
    "21-1099.00": {"occupation_name": "Community and Social Service Specialists", "overall_exposure": 0.25},
    "11-1011.00": {"occupation_name": "Chief Executives", "overall_exposure": 0.30},
    "11-2031.00": {"occupation_name": "Public Relations Managers", "overall_exposure": 0.33},
    "11-9081.00": {"occupation_name": "Lodging Managers", "overall_exposure": 0.32},
    "13-1041.00": {"occupation_name": "Compliance Officers", "overall_exposure": 0.40},
    "19-3031.00": {"occupation_name": "Clinical, Counseling Psychologists", "overall_exposure": 0.18},
    "19-3032.00": {"occupation_name": "Industrial-Organizational Psychologists", "overall_exposure": 0.28},
    "21-1011.00": {"occupation_name": "Substance Abuse Counselors", "overall_exposure": 0.17},
    "21-1012.00": {"occupation_name": "Educational, Guidance Counselors", "overall_exposure": 0.20},
    "25-2021.00": {"occupation_name": "Elementary School Teachers", "overall_exposure": 0.22},
    "25-2031.00": {"occupation_name": "Secondary School Teachers", "overall_exposure": 0.24},
    "25-3999.00": {"occupation_name": "Teachers and Instructors, All Other", "overall_exposure": 0.25},

    # Low exposure (physical / relational)
    "29-1141.00": {"occupation_name": "Registered Nurses", "overall_exposure": 0.18},
    "29-1215.00": {"occupation_name": "Family Medicine Physicians", "overall_exposure": 0.15},
    "29-2061.00": {"occupation_name": "Licensed Practical Nurses", "overall_exposure": 0.20},
    "31-1120.00": {"occupation_name": "Home Health and Personal Care Aides", "overall_exposure": 0.12},
    "33-3021.00": {"occupation_name": "Detectives and Criminal Investigators", "overall_exposure": 0.25},
    "33-1011.00": {"occupation_name": "First-Line Police Supervisors", "overall_exposure": 0.22},
    "37-1011.00": {"occupation_name": "First-Line Supervisors of Housekeeping Workers", "overall_exposure": 0.20},
    "45-2092.00": {"occupation_name": "Farmworkers and Laborers", "overall_exposure": 0.15},
    "47-2061.00": {"occupation_name": "Construction Laborers", "overall_exposure": 0.13},
    "47-2111.00": {"occupation_name": "Electricians", "overall_exposure": 0.18},
    "49-3023.00": {"occupation_name": "Automotive Service Technicians", "overall_exposure": 0.20},
    "35-1012.00": {"occupation_name": "First-Line Supervisors of Food Preparation Workers", "overall_exposure": 0.22},

    # Climate / sustainability roles (lower risk — specialised human judgment)
    "19-2041.00": {"occupation_name": "Environmental Scientists and Specialists", "overall_exposure": 0.32},
    "19-2041.01": {"occupation_name": "Climate Change Policy Analysts", "overall_exposure": 0.28},
    "11-9121.02": {"occupation_name": "Water Resource Specialists", "overall_exposure": 0.30},
    "17-2081.00": {"occupation_name": "Environmental Engineers", "overall_exposure": 0.35},
    "13-1199.05": {"occupation_name": "Sustainability Specialists", "overall_exposure": 0.30},
    "11-9199.11": {"occupation_name": "Brownfield Redevelopment Specialists", "overall_exposure": 0.25},

    # Project management / strategy
    "11-3021.00": {"occupation_name": "Computer and Information Systems Managers", "overall_exposure": 0.45},
    "11-9199.00": {"occupation_name": "Managers, All Other", "overall_exposure": 0.35},
    "13-1082.00": {"occupation_name": "Project Management Specialists", "overall_exposure": 0.40},
    "11-2022.00": {"occupation_name": "Sales Managers", "overall_exposure": 0.42},

    # Data roles
    "15-2051.00": {"occupation_name": "Data Scientists", "overall_exposure": 0.58},
    "15-2051.01": {"occupation_name": "Business Intelligence Analysts", "overall_exposure": 0.62},
    "15-1243.00": {"occupation_name": "Database Architects", "overall_exposure": 0.55},
    "15-1241.00": {"occupation_name": "Computer Network Architects", "overall_exposure": 0.50},
}

output = Path(__file__).parent.parent / "data" / "economic_index.json"
output.parent.mkdir(parents=True, exist_ok=True)
with open(output, "w") as f:
    json.dump(OCCUPATIONS, f, indent=2)
print(f"Saved {len(OCCUPATIONS)} occupations to {output}")
