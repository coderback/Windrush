# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windrush is a UK-focused job board platform for international job seekers (students/graduates) seeking employment with visa sponsorship. The name is inspired by the Windrush generation, symbolizing new opportunities for those coming to the UK.

**Key Features:**
- Job listings exclusively from visa-sponsor licensed employers
- AI-driven job recommendations 
- Speculative applications to sponsor companies
- Multi-document support (CVs, cover letters)
- Real-time notifications
- Premium subscription model

## Architecture Overview

**Current State:** This is a greenfield project in the planning phase with no implementation yet. The repository currently contains only documentation files outlining the system design and requirements.

**Planned Architecture:**
- **Frontend:** React.js with Next.js (TypeScript), responsive design
- **Backend:** Node.js with Express/NestJS OR Django (Python) - decision pending
- **Database:** PostgreSQL primary, Redis for caching, Elasticsearch for search
- **Storage:** AWS S3 for file uploads (CVs, documents)
- **AI/ML:** Python-based recommendation engine (scikit-learn/Pytorch)
- **Infrastructure:** AWS (EC2, RDS, ELB, CloudFront)

**Service Architecture (Planned):**
- User Service (auth, profiles, subscriptions)
- Job Service (listings, search, company management)
- Application Service (job applications, speculative applications)
- AI Recommendation Service (ML-based job matching)
- Notification Service (email, in-app notifications)
- Admin Service (content management, analytics)

## Development Phases

The project follows a 4-phase development plan:

1. **Phase 1 (3-4 months):** MVP - Core job board functionality
2. **Phase 2 (+2 months):** Enhanced AI matching and user experience
3. **Phase 3 (+3 months):** Employer portal and self-service
4. **Phase 4 (+2-3 months):** Refinement, scale, and mobile

## Key Requirements

**Functional Requirements:**
- Handle 50,000+ users with high scalability
- Support visa sponsorship compliance (UK Skilled Worker visa)
- Multi-document application system
- Real-time notifications and messaging
- Premium subscription features

**Compliance:**
- GDPR data protection compliance
- UK visa regulation adherence
- Secure file handling and storage
- Privacy-by-design architecture

## Tech Stack Decisions

**Language Choice:** TypeScript/JavaScript for full-stack consistency, with Python for ML components

**Framework Decision Pending:** 
- Option A: Node.js/Express/NestJS for unified JavaScript stack
- Option B: Django/Python for rapid development with built-in admin

**Database:** PostgreSQL chosen for ACID compliance and full-text search capabilities

**Deployment:** AWS cloud infrastructure with auto-scaling and load balancing

## File Structure Context

The repository currently contains documentation in the `Documents/` folder:
- System design and architecture specifications
- Functional and non-functional requirements
- Tech stack analysis and decisions
- Development roadmap and compliance requirements

## Future Implementation Notes

When implementation begins:
- Start with database schema design based on Documents/Database Design.txt
- Implement user authentication and basic CRUD operations first
- Set up CI/CD pipeline with automated testing
- Implement file upload to S3 with proper security
- Create admin interface for initial job curation
- Build responsive React frontend with job search functionality

## Compliance Considerations

- All user data handling must be GDPR compliant
- File uploads require virus scanning and access controls
- Implement audit logging for sensitive operations
- Ensure data residency requirements for UK/EU users
- Regular security audits and penetration testing required

## Integration Points

- Government sponsor license API (for company verification)
- Email services (SendGrid/AWS SES)
- Payment processing (Stripe for subscriptions)
- Cloud storage (AWS S3 with CDN)
- Analytics and monitoring (CloudWatch/ELK stack)