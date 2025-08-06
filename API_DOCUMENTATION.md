# Windrush API Documentation

## Overview

The Windrush API is a RESTful API built with Django REST Framework that provides endpoints for managing a UK visa-sponsorship focused job board platform.

**Base URL**: `http://localhost:8000/api`

## Authentication

The API uses Token-based authentication. Include the token in the Authorization header:

```
Authorization: Token <your_token_here>
```

## API Endpoints Overview

### Authentication & Accounts (`/api/auth/`)
- User registration, login, logout
- Profile management
- Password management
- Account statistics

### Companies (`/api/companies/`)
- Company listings with sponsor information
- Company profiles and reviews
- Company search and filtering

### Jobs (`/api/jobs/`)
- Job listings with visa sponsorship details
- Advanced job search and filtering
- Saved jobs and job alerts

### Applications (`/api/applications/`)
- Job applications and speculative applications
- Application tracking and status updates
- Application messaging

## Authentication Endpoints

### POST `/api/auth/register/`
Register a new user account.

**Request Body:**
```json
{
  "email": "user@example.com",
  "username": "username",
  "first_name": "John",
  "last_name": "Doe",
  "password": "secure_password123",
  "password_confirm": "secure_password123",
  "user_type": "job_seeker"  // or "employer"
}
```

**Response:**
```json
{
  "message": "Registration successful",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "username": "username",
    "first_name": "John",
    "last_name": "Doe",
    "full_name": "John Doe",
    "user_type": "job_seeker",
    "is_verified": false,
    "is_premium": false,
    "created_at": "2025-01-08T10:00:00Z"
  },
  "token": "abc123def456..."
}
```

### POST `/api/auth/login/`
Authenticate user and get access token.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "secure_password123"
}
```

**Response:**
```json
{
  "message": "Login successful",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "username": "username",
    "full_name": "John Doe",
    "user_type": "job_seeker",
    "is_verified": false,
    "is_premium": false
  },
  "token": "abc123def456..."
}
```

### POST `/api/auth/logout/`
**Authentication Required**

Logout current user and invalidate token.

**Response:**
```json
{
  "message": "Logout successful"
}
```

## Profile Management

### GET `/api/auth/profile/`
**Authentication Required**

Get current user's profile information.

**Response:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "username": "username",
  "first_name": "John",
  "last_name": "Doe",
  "full_name": "John Doe",
  "user_type": "job_seeker",
  "is_verified": false,
  "is_premium": false,
  "created_at": "2025-01-08T10:00:00Z",
  "updated_at": "2025-01-08T10:00:00Z"
}
```

### PATCH `/api/auth/profile/`
**Authentication Required**

Update current user's basic profile information.

**Request Body:**
```json
{
  "first_name": "John",
  "last_name": "Smith",
  "username": "johnsmith"
}
```

### GET `/api/auth/job-seeker-profile/`
**Authentication Required** (Job Seekers Only)

Get detailed job seeker profile.

**Response:**
```json
{
  "user": {
    "id": 1,
    "email": "user@example.com",
    "full_name": "John Doe",
    "user_type": "job_seeker"
  },
  "phone_number": "+44 7700 900123",
  "nationality": "Indian",
  "visa_status": "student",
  "visa_expiry_date": "2025-12-31",
  "education_level": "Master's Degree",
  "field_of_study": "Computer Science",
  "university": "University of Edinburgh",
  "graduation_year": 2024,
  "years_of_experience": 2,
  "job_type_preferences": ["full_time", "graduate_scheme"],
  "preferred_locations": ["London", "Manchester"],
  "preferred_industries": ["Technology", "Finance"],
  "expected_salary_min": 30000,
  "expected_salary_max": 45000,
  "skills": ["Python", "JavaScript", "React", "Django"],
  "bio": "Passionate software developer with experience in web applications...",
  "is_profile_public": false,
  "is_available_for_work": true,
  "primary_cv": "/media/cvs/john_doe_cv.pdf",
  "created_at": "2025-01-08T10:00:00Z",
  "updated_at": "2025-01-08T10:15:00Z"
}
```

### PATCH `/api/auth/job-seeker-profile/`
**Authentication Required** (Job Seekers Only)

Update job seeker profile information.

**Request Body:**
```json
{
  "phone_number": "+44 7700 900123",
  "skills": ["Python", "Django", "PostgreSQL"],
  "bio": "Updated bio text...",
  "expected_salary_min": 35000,
  "is_available_for_work": true
}
```

## Password Management

### POST `/api/auth/change-password/`
**Authentication Required**

Change user's password.

**Request Body:**
```json
{
  "old_password": "current_password",
  "new_password": "new_secure_password123",
  "new_password_confirm": "new_secure_password123"
}
```

**Response:**
```json
{
  "message": "Password changed successfully. Please login again."
}
```

### POST `/api/auth/password-reset/`
Request password reset (sends email).

**Request Body:**
```json
{
  "email": "user@example.com"
}
```

**Response:**
```json
{
  "message": "Password reset instructions sent to user@example.com"
}
```

## Account Management

### GET `/api/auth/stats/`
**Authentication Required**

Get user account statistics.

**Response (Job Seeker):**
```json
{
  "total_applications": 15,
  "active_applications": 8,
  "successful_applications": 2,
  "saved_jobs": 12,
  "profile_completion": 85
}
```

**Response (Employer):**
```json
{
  "companies_managed": 1,
  "jobs_posted": 5,
  "active_jobs": 3,
  "total_applications_received": 24
}
```

### POST `/api/auth/verify-email/`
**Authentication Required**

Verify user's email address.

**Response:**
```json
{
  "message": "Email verified successfully"
}
```

### DELETE `/api/auth/delete-account/`
**Authentication Required**

Permanently delete user account.

**Response:**
```json
{
  "message": "Account deleted successfully"
}
```

## Error Responses

### Validation Error (400)
```json
{
  "field_name": ["Error message for this field"],
  "non_field_errors": ["General error message"]
}
```

### Authentication Error (401)
```json
{
  "detail": "Authentication credentials were not provided."
}
```

### Permission Denied (403)
```json
{
  "detail": "You do not have permission to perform this action."
}
```

### Not Found (404)
```json
{
  "detail": "Not found."
}
```

### Server Error (500)
```json
{
  "detail": "Internal server error."
}
```

## Testing the API

### Using cURL

1. **Register a new user:**
```bash
curl -X POST http://localhost:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "username": "testuser",
    "first_name": "Test",
    "last_name": "User",
    "password": "testpass123",
    "password_confirm": "testpass123",
    "user_type": "job_seeker"
  }'
```

2. **Login:**
```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "testpass123"
  }'
```

3. **Get profile (replace TOKEN):**
```bash
curl -X GET http://localhost:8000/api/auth/profile/ \
  -H "Authorization: Token YOUR_TOKEN_HERE"
```

### Using the Test Script

We've included a comprehensive test script:

```bash
python test_api.py
```

This will test all authentication endpoints and verify the API is working correctly.

## Development Notes

- All timestamps are in UTC ISO format
- File uploads use multipart/form-data
- JSON requests should use `Content-Type: application/json`
- Token authentication is stateless
- Tokens don't expire automatically (implement refresh logic if needed)

## Coming Soon

The following endpoint groups are planned:

### Companies API
- `GET /api/companies/` - List sponsor companies
- `GET /api/companies/{id}/` - Company details
- `POST /api/companies/{id}/reviews/` - Add company review

### Jobs API  
- `GET /api/jobs/` - List jobs with filtering
- `GET /api/jobs/{id}/` - Job details
- `POST /api/jobs/{id}/save/` - Save/bookmark job

### Applications API
- `GET /api/applications/` - List user's applications
- `POST /api/applications/` - Submit job application
- `POST /api/applications/speculative/` - Submit speculative application

## Companies API

### GET `/api/companies/`
List all companies with filtering and search capabilities.

**Query Parameters:**
- `search` - Search in company name, description, or industry
- `industry` - Filter by industry (partial match)
- `location` - Filter by city or region (partial match)
- `company_size` - Filter by company size
- `sponsor_status` - Filter by sponsor status (`active`, `inactive`, `pending`)
- `visa_types` - Filter by supported visa types (can specify multiple)
- `has_active_jobs` - Filter companies with active job postings (`true`/`false`)
- `is_featured` - Filter featured companies (`true`/`false`)
- `ordering` - Sort results (`name`, `-name`, `created_at`, `-created_at`, `total_jobs_posted`, `-total_jobs_posted`)

**Response:**
```json
{
  "count": 50,
  "next": "http://localhost:8000/api/companies/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "TechCorp Ltd",
      "slug": "techcorp-ltd",
      "industry": "Technology",
      "company_size": "medium",
      "city": "London",
      "region": "Greater London",
      "logo": "/media/logos/techcorp.png",
      "is_sponsor": true,
      "sponsor_status": "active",
      "sponsor_types": ["skilled_worker", "intra_company_transfer"],
      "active_jobs_count": 5,
      "can_sponsor_skilled_worker": 1,
      "is_featured": true,
      "is_premium_partner": false
    }
  ]
}
```

### POST `/api/companies/`
**Authentication Required**

Create a new company profile.

**Request Body:**
```json
{
  "name": "TechCorp Ltd",
  "website": "https://techcorp.com",
  "email": "jobs@techcorp.com",
  "phone": "+44 20 1234 5678",
  "description": "Leading technology company specializing in AI and machine learning...",
  "industry": "Technology",
  "company_size": "medium",
  "founded_year": 2015,
  "headquarters_address": "123 Tech Street, London",
  "city": "London",
  "region": "Greater London",
  "postcode": "SW1A 1AA",
  "sponsor_license_number": "ABC123456789",
  "sponsor_types": ["skilled_worker", "intra_company_transfer"],
  "benefits": ["Health insurance", "Flexible working", "Visa sponsorship"],
  "company_values": ["Innovation", "Diversity", "Growth"],
  "linkedin_url": "https://linkedin.com/company/techcorp",
  "twitter_url": "https://twitter.com/techcorp"
}
```

### GET `/api/companies/{slug}/`
Get detailed information about a specific company.

**Response:**
```json
{
  "id": 1,
  "name": "TechCorp Ltd",
  "slug": "techcorp-ltd",
  "website": "https://techcorp.com",
  "email": "jobs@techcorp.com",
  "phone": "+44 20 1234 5678",
  "description": "Leading technology company...",
  "industry": "Technology",
  "company_size": "medium",
  "founded_year": 2015,
  "headquarters_address": "123 Tech Street, London",
  "city": "London",
  "region": "Greater London",
  "country": "United Kingdom",
  "postcode": "SW1A 1AA",
  "is_sponsor": true,
  "sponsor_license_number": "ABC123456789",
  "sponsor_status": "active",
  "sponsor_types": ["skilled_worker", "intra_company_transfer"],
  "sponsor_verified_date": "2024-01-15T10:00:00Z",
  "logo": "/media/logos/techcorp.png",
  "banner_image": "/media/banners/techcorp.jpg",
  "benefits": ["Health insurance", "Flexible working", "Visa sponsorship"],
  "company_values": ["Innovation", "Diversity", "Growth"],
  "linkedin_url": "https://linkedin.com/company/techcorp",
  "twitter_url": "https://twitter.com/techcorp",
  "glassdoor_url": null,
  "is_featured": true,
  "is_premium_partner": false,
  "total_jobs_posted": 25,
  "total_hires_made": 15,
  "active_jobs_count": 5,
  "can_sponsor_skilled_worker": 1,
  "average_rating": 4.2,
  "review_count": 8,
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-20T15:30:00Z"
}
```

### PATCH/PUT `/api/companies/{slug}/`
**Authentication Required** (Company owner or admin only)

Update company information.

### DELETE `/api/companies/{slug}/`
**Authentication Required** (Company owner or admin only)

Delete a company profile.

## Company Reviews

### GET `/api/companies/{slug}/reviews/`
Get reviews for a specific company.

**Response:**
```json
{
  "count": 8,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "company": 1,
      "reviewer_name": "John Smith",
      "reviewer_is_anonymous": false,
      "title": "Great place to work with excellent visa support",
      "review_text": "TechCorp provided excellent support throughout my visa sponsorship process...",
      "overall_rating": 5,
      "work_life_balance": 4,
      "compensation": 4,
      "career_opportunities": 5,
      "management": 4,
      "culture": 5,
      "job_title": "Software Engineer",
      "employment_status": "current",
      "employment_length": "2_years",
      "received_sponsorship": true,
      "sponsorship_experience": "Very smooth process, HR was very helpful...",
      "helpful_count": 5,
      "created_at": "2024-01-18T14:30:00Z"
    }
  ]
}
```

### POST `/api/companies/{slug}/reviews/`
**Authentication Required**

Create a review for a company.

**Request Body:**
```json
{
  "title": "Great place to work with excellent visa support",
  "review_text": "TechCorp provided excellent support throughout my visa sponsorship process...",
  "overall_rating": 5,
  "work_life_balance": 4,
  "compensation": 4,
  "career_opportunities": 5,
  "management": 4,
  "culture": 5,
  "job_title": "Software Engineer",
  "employment_status": "current",
  "employment_length": "2_years",
  "received_sponsorship": true,
  "sponsorship_experience": "Very smooth process, HR was very helpful...",
  "is_anonymous": false
}
```

### POST `/api/companies/reviews/{review_id}/helpful/`
**Authentication Required**

Mark a review as helpful.

**Response:**
```json
{
  "message": "Review marked as helpful",
  "helpful_count": 6
}
```

## Company Statistics and Search

### GET `/api/companies/search/`
Advanced company search with comprehensive filtering.

**Query Parameters:**
- All the same parameters as `/api/companies/` plus additional validation

### GET `/api/companies/stats/`
Get overall company statistics.

**Response:**
```json
{
  "total_companies": 150,
  "sponsor_companies": 125,
  "active_sponsors": 120,
  "companies_with_jobs": 95,
  "featured_companies": 12,
  "top_industries": [
    {"industry": "Technology", "count": 45},
    {"industry": "Finance", "count": 30},
    {"industry": "Healthcare", "count": 25}
  ],
  "top_locations": [
    {"city": "London", "region": "Greater London", "count": 60},
    {"city": "Manchester", "region": "Greater Manchester", "count": 25}
  ]
}
```

### GET `/api/companies/featured/`
Get featured companies for homepage display.

**Response:**
```json
[
  {
    "id": 1,
    "name": "TechCorp Ltd",
    "slug": "techcorp-ltd",
    "industry": "Technology",
    "city": "London",
    "logo": "/media/logos/techcorp.png",
    "is_sponsor": true,
    "sponsor_status": "active",
    "active_jobs_count": 5
  }
]
```

Stay tuned for updates as we implement the remaining endpoints!