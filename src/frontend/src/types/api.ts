// API Response Types
export interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  phone: string | null;
  date_of_birth: string | null;
  location: string | null;
  visa_status: 'citizen' | 'permanent_resident' | 'work_visa' | 'student_visa' | 'other' | null;
  linkedin_url: string | null;
  github_url: string | null;
  portfolio_url: string | null;
  skills: string[];
  experience_level: 'entry' | 'junior' | 'mid' | 'senior' | 'lead' | 'executive' | null;
  preferred_job_types: string[];
  preferred_locations: string[];
  salary_expectation_min: number | null;
  salary_expectation_max: number | null;
  currency: string;
  is_open_to_remote: boolean;
  is_seeking_sponsorship: boolean;
  is_active: boolean;
  date_joined: string;
  last_login: string | null;
}

export interface Company {
  id: number;
  name: string;
  slug: string;
  industry: string;
  company_size: string;
  city: string;
  region: string;
  logo: string | null;
  is_sponsor: boolean;
  sponsor_status: string;
  sponsor_types: string[];
  active_jobs_count: number;
  can_sponsor_skilled_worker: boolean;
  is_featured: boolean;
  is_premium_partner: boolean;
}

export interface Job {
  id: number;
  title: string;
  slug: string;
  company: Company;
  location: string;
  location_type: 'on_site' | 'remote' | 'hybrid';
  job_type: 'full_time' | 'part_time' | 'contract' | 'temporary' | 'internship';
  salary_min: number | null;
  salary_max: number | null;
  currency: string;
  description: string;
  requirements: string;
  benefits: string[];
  visa_sponsorship_available: boolean;
  visa_types_supported: string[];
  experience_level: 'entry' | 'junior' | 'mid' | 'senior' | 'lead' | 'executive';
  skills_required: string[];
  application_deadline: string | null;
  is_featured: boolean;
  is_urgent: boolean;
  status: string;
  posted_date: string;
  application_count: number;
  days_since_posted: number;
}

export interface Application {
  id: number;
  job: Job;
  applicant: User;
  status: 'pending' | 'reviewing' | 'shortlisted' | 'interviewing' | 'offered' | 'rejected' | 'withdrawn';
  cover_letter: string;
  resume: string;
  portfolio_links: string[];
  expected_salary: number | null;
  available_start_date: string | null;
  requires_sponsorship: boolean;
  applied_at: string;
  updated_at: string;
}

// Authentication Types
export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterData {
  email: string;
  username: string;
  password: string;
  password_confirm: string;
  first_name: string;
  last_name: string;
  user_type: string;
}

export interface AuthResponse {
  user: User;
  token?: string;
  message: string;
  verification_required?: boolean;
}

// API Search Parameters
export interface JobSearchParams {
  search?: string;
  location?: string;
  job_type?: string;
  experience_level?: string;
  salary_min?: number;
  salary_max?: number;
  visa_sponsorship?: boolean;
  location_type?: string;
  is_featured?: boolean;
  company?: string;
  skills?: string[];
  posted_within?: 'today' | 'week' | 'month';
  ordering?: string;
  page?: number;
}

export interface CompanySearchParams {
  search?: string;
  industry?: string;
  location?: string;
  company_size?: string;
  sponsor_status?: string;
  visa_types?: string[];
  has_active_jobs?: boolean;
  is_featured?: boolean;
  ordering?: string;
  page?: number;
}

// Paginated Response
export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// API Error Response
export interface ApiError {
  detail?: string;
  [key: string]: string[] | string | undefined;
}