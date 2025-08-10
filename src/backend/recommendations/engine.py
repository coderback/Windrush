import time
import re
from typing import List, Dict, Tuple, Optional
from django.db.models import QuerySet, Q
from django.utils import timezone
from accounts.models import User
from jobs.models import Job
from .models import UserJobPreference, JobRecommendation, RecommendationBatch
import logging

logger = logging.getLogger(__name__)


class JobRecommendationEngine:
    """
    Rule-based job recommendation engine for Windrush
    
    This engine considers multiple factors:
    - Skills matching (job requirements vs user skills)
    - Location preferences and remote work options
    - Salary expectations vs job salary range
    - Company size and culture preferences
    - Experience level matching
    - Visa sponsorship requirements
    - Industry preferences
    - Previously applied jobs (to avoid duplicates)
    """
    
    def __init__(self, algorithm_version: str = 'rule_based_v1'):
        self.algorithm_version = algorithm_version
        self.weights = {
            'skills': 0.25,
            'location': 0.20,
            'salary': 0.15,
            'company': 0.15,
            'experience': 0.15,
            'sponsorship': 0.10
        }
    
    def generate_recommendations(
        self, 
        user: User, 
        limit: int = 10, 
        refresh: bool = False
    ) -> List[JobRecommendation]:
        """
        Generate job recommendations for a user
        
        Args:
            user: User to generate recommendations for
            limit: Maximum number of recommendations to generate
            refresh: Whether to generate fresh recommendations or return existing
            
        Returns:
            List of JobRecommendation objects
        """
        start_time = time.time()
        
        # Get or create user preferences
        preferences, _ = UserJobPreference.objects.get_or_create(user=user)
        
        # Check if we should use cached recommendations
        if not refresh:
            existing = JobRecommendation.objects.filter(
                user=user,
                created_at__gte=timezone.now() - timezone.timedelta(hours=24)
            )[:limit]
            
            if existing.count() >= limit:
                logger.info(f"Returning {existing.count()} cached recommendations for {user.email}")
                return list(existing)
        
        # Get eligible jobs (active, not applied to)
        eligible_jobs = self._get_eligible_jobs(user, preferences)
        
        if not eligible_jobs.exists():
            logger.warning(f"No eligible jobs found for user {user.email}")
            return []
        
        # Score each job
        scored_jobs = []
        for job in eligible_jobs[:200]:  # Limit to avoid performance issues
            score_data = self._calculate_job_score(job, user, preferences)
            if score_data['overall_score'] > 0.3:  # Minimum threshold
                scored_jobs.append((job, score_data))
        
        # Sort by score and take top results
        scored_jobs.sort(key=lambda x: x[1]['overall_score'], reverse=True)
        top_jobs = scored_jobs[:limit]
        
        # Create recommendation objects
        recommendations = []
        for job, score_data in top_jobs:
            # Delete existing recommendation if refreshing
            if refresh:
                JobRecommendation.objects.filter(user=user, job=job).delete()
            
            recommendation, created = JobRecommendation.objects.get_or_create(
                user=user,
                job=job,
                defaults={
                    'match_score': score_data['overall_score'],
                    'skill_match_score': score_data['skill_score'],
                    'location_match_score': score_data['location_score'],
                    'salary_match_score': score_data['salary_score'],
                    'company_match_score': score_data['company_score'],
                    'experience_match_score': score_data['experience_score'],
                    'match_reasons': score_data['reasons'],
                    'recommendation_algorithm': self.algorithm_version
                }
            )
            
            recommendations.append(recommendation)
        
        # Create batch record
        if recommendations:
            generation_time_ms = int((time.time() - start_time) * 1000)
            total_recs = len(recommendations)
            avg_score = sum(r.match_score for r in recommendations) / total_recs if total_recs > 0 else 0
            
            RecommendationBatch.objects.create(
                user=user,
                algorithm_version=self.algorithm_version,
                total_recommendations=total_recs,
                average_score=avg_score,
                generation_time_ms=generation_time_ms,
                preferences_snapshot=self._create_preferences_snapshot(preferences)
            )
            
            logger.info(f"Generated {total_recs} recommendations for {user.email} in {generation_time_ms}ms")
        
        return recommendations
    
    def _get_eligible_jobs(self, user: User, preferences: UserJobPreference) -> QuerySet:
        """Get jobs eligible for recommendation"""
        # Start with active jobs from sponsor companies
        jobs = Job.objects.filter(
            status='active',
            company__is_sponsor=True,
            company__sponsor_status='active'
        ).select_related('company')
        
        # Exclude already applied jobs
        applied_jobs = user.applications.values_list('job_id', flat=True)
        jobs = jobs.exclude(id__in=applied_jobs)
        
        # Filter by visa sponsorship if required
        if preferences.requires_sponsorship:
            # Only include jobs from companies that can sponsor needed visa types
            if preferences.visa_types_needed:
                for visa_type in preferences.visa_types_needed:
                    jobs = jobs.filter(company__sponsor_types__contains=[visa_type])
            else:
                # Default to skilled worker visa
                jobs = jobs.filter(company__sponsor_types__contains=['skilled_worker'])
        
        # Filter by preferred industries
        if preferences.preferred_industries:
            jobs = jobs.filter(company__industry__in=preferences.preferred_industries)
        
        # Filter by company size preferences
        if preferences.preferred_company_sizes:
            jobs = jobs.filter(company__company_size__in=preferences.preferred_company_sizes)
        
        # Exclude companies user wants to avoid
        if preferences.avoid_companies:
            jobs = jobs.exclude(company_id__in=preferences.avoid_companies)
        
        # Filter by location if not open to remote
        if not preferences.open_to_remote and preferences.preferred_locations:
            location_filter = Q()
            for location in preferences.preferred_locations:
                location_filter |= Q(location__icontains=location) | Q(company__city__icontains=location)
            jobs = jobs.filter(location_filter)
        
        return jobs.order_by('-created_at')
    
    def _calculate_job_score(self, job, user: User, preferences: UserJobPreference) -> Dict:
        """Calculate comprehensive match score for a job"""
        scores = {}
        reasons = []
        
        # Skills matching (25% weight)
        scores['skill_score'] = self._calculate_skill_score(job, preferences, reasons)
        
        # Location matching (20% weight)
        scores['location_score'] = self._calculate_location_score(job, preferences, reasons)
        
        # Salary matching (15% weight)
        scores['salary_score'] = self._calculate_salary_score(job, preferences, reasons)
        
        # Company matching (15% weight)
        scores['company_score'] = self._calculate_company_score(job, preferences, reasons)
        
        # Experience matching (15% weight)
        scores['experience_score'] = self._calculate_experience_score(job, preferences, reasons)
        
        # Sponsorship matching (10% weight)
        scores['sponsorship_score'] = self._calculate_sponsorship_score(job, preferences, reasons)
        
        # Calculate weighted overall score
        overall_score = (
            scores['skill_score'] * self.weights['skills'] +
            scores['location_score'] * self.weights['location'] +
            scores['salary_score'] * self.weights['salary'] +
            scores['company_score'] * self.weights['company'] +
            scores['experience_score'] * self.weights['experience'] +
            scores['sponsorship_score'] * self.weights['sponsorship']
        )
        
        return {
            'overall_score': overall_score,
            'skill_score': scores['skill_score'],
            'location_score': scores['location_score'],
            'salary_score': scores['salary_score'],
            'company_score': scores['company_score'],
            'experience_score': scores['experience_score'],
            'sponsorship_score': scores['sponsorship_score'],
            'reasons': reasons
        }
    
    def _calculate_skill_score(self, job, preferences: UserJobPreference, reasons: List) -> float:
        """Calculate skill matching score"""
        if not preferences.key_skills or not job.required_skills:
            return 0.5  # Neutral score when no skills data
        
        user_skills = {skill.lower().strip() for skill in preferences.key_skills}
        job_skills = {skill.lower().strip() for skill in job.required_skills}
        
        # Check for avoid keywords
        job_text = f"{job.title} {job.description} {' '.join(job.required_skills)}".lower()
        for avoid_keyword in preferences.avoid_keywords:
            if avoid_keyword.lower() in job_text:
                reasons.append(f"Job contains avoided keyword: {avoid_keyword}")
                return 0.0  # Exclude job if contains avoided keywords
        
        # Calculate skill overlap
        matching_skills = user_skills.intersection(job_skills)
        if matching_skills:
            skill_match_ratio = len(matching_skills) / len(job_skills)
            reasons.append(f"Matches {len(matching_skills)} key skills: {', '.join(list(matching_skills)[:3])}")
            return min(1.0, skill_match_ratio * 1.2)  # Bonus for good matches
        
        # Partial matching for similar skills
        partial_matches = 0
        for user_skill in user_skills:
            for job_skill in job_skills:
                if user_skill in job_skill or job_skill in user_skill:
                    partial_matches += 1
                    break
        
        if partial_matches > 0:
            partial_ratio = partial_matches / len(job_skills)
            reasons.append(f"Partial skill match ({partial_matches} related skills)")
            return partial_ratio * 0.7
        
        return 0.3  # Low score for no skill matches
    
    def _calculate_location_score(self, job, preferences: UserJobPreference, reasons: List) -> float:
        """Calculate location matching score"""
        # Remote work gets high score if user is open to it
        if job.is_remote and preferences.open_to_remote:
            reasons.append("Remote work available")
            return 1.0
        
        # Hybrid work
        if job.is_hybrid and preferences.open_to_hybrid:
            reasons.append("Hybrid work available")
            return 0.9
        
        # Location matching
        if preferences.preferred_locations:
            job_location = job.location.lower() if job.location else ""
            company_location = job.company.city.lower() if job.company.city else ""
            
            for pref_location in preferences.preferred_locations:
                pref_location_lower = pref_location.lower()
                if (pref_location_lower in job_location or 
                    pref_location_lower in company_location or
                    job_location in pref_location_lower or
                    company_location in pref_location_lower):
                    reasons.append(f"Location matches preference: {pref_location}")
                    return 0.8
        
        # Default score if no location preferences
        if not preferences.preferred_locations:
            return 0.6
        
        return 0.2  # Low score for location mismatch
    
    def _calculate_salary_score(self, job, preferences: UserJobPreference, reasons: List) -> float:
        """Calculate salary matching score"""
        if not job.salary_min or not preferences.min_salary:
            return 0.5  # Neutral when salary data missing
        
        # Convert to same currency if needed (assume GBP for now)
        job_min = job.salary_min
        job_max = job.salary_max or job_min * 1.2
        user_min = preferences.min_salary
        user_max = preferences.max_salary or user_min * 1.5
        
        # Check if salary ranges overlap
        if job_max >= user_min and job_min <= user_max:
            # Calculate overlap ratio
            overlap_start = max(job_min, user_min)
            overlap_end = min(job_max, user_max)
            overlap_size = overlap_end - overlap_start
            
            user_range = user_max - user_min
            overlap_ratio = overlap_size / user_range if user_range > 0 else 1.0
            
            if job_min >= user_min:
                reasons.append(f"Salary meets expectations (£{job_min:,}+)")
                return min(1.0, 0.8 + overlap_ratio * 0.2)
            else:
                reasons.append(f"Salary partially meets expectations")
                return 0.6 + overlap_ratio * 0.2
        
        # Check if job salary is close to expectations
        if job_max >= user_min * 0.8:
            reasons.append("Salary close to expectations")
            return 0.4
        
        return 0.1  # Low score for salary mismatch
    
    def _calculate_company_score(self, job, preferences: UserJobPreference, reasons: List) -> float:
        """Calculate company matching score"""
        score = 0.5  # Base score
        
        # Company size preference
        if preferences.preferred_company_sizes and job.company.company_size:
            if job.company.company_size in preferences.preferred_company_sizes:
                score += 0.2
                reasons.append(f"Company size matches preference: {job.company.company_size}")
        
        # Industry preference
        if preferences.preferred_industries and job.company.industry:
            if job.company.industry in preferences.preferred_industries:
                score += 0.3
                reasons.append(f"Industry matches preference: {job.company.industry}")
        
        # Avoid companies check
        if preferences.avoid_companies and job.company.id in preferences.avoid_companies:
            return 0.0  # Exclude avoided companies
        
        return min(1.0, score)
    
    def _calculate_experience_score(self, job, preferences: UserJobPreference, reasons: List) -> float:
        """Calculate experience level matching score"""
        if not job.experience_required:
            return 0.6  # Neutral when no experience requirement
        
        experience_levels = {
            'entry': 1,
            'mid': 2, 
            'senior': 3,
            'lead': 4,
            'executive': 5
        }
        
        user_level = experience_levels.get(preferences.experience_level, 2)
        job_level = experience_levels.get(job.experience_required, 2)
        
        level_diff = abs(user_level - job_level)
        
        if level_diff == 0:
            reasons.append(f"Experience level perfect match: {preferences.experience_level}")
            return 1.0
        elif level_diff == 1:
            reasons.append(f"Experience level close match")
            return 0.8
        elif level_diff == 2:
            return 0.5
        else:
            return 0.2
    
    def _calculate_sponsorship_score(self, job, preferences: UserJobPreference, reasons: List) -> float:
        """Calculate visa sponsorship matching score"""
        if not preferences.requires_sponsorship:
            return 1.0  # Perfect score if no sponsorship needed
        
        if not job.company.is_sponsor or job.company.sponsor_status != 'active':
            return 0.0  # Cannot recommend non-sponsor companies
        
        # Check if company can sponsor required visa types
        if preferences.visa_types_needed:
            company_sponsor_types = job.company.sponsor_types or []
            for visa_type in preferences.visa_types_needed:
                if visa_type in company_sponsor_types:
                    reasons.append(f"Company can sponsor {visa_type} visa")
                    return 1.0
            return 0.3  # Company is sponsor but may not support specific visa type
        
        # Default: company is active sponsor
        reasons.append("Company is licensed visa sponsor")
        return 0.9
    
    def _create_preferences_snapshot(self, preferences: UserJobPreference) -> Dict:
        """Create a snapshot of user preferences for analysis"""
        return {
            'preferred_locations': preferences.preferred_locations,
            'experience_level': preferences.experience_level,
            'min_salary': preferences.min_salary,
            'max_salary': preferences.max_salary,
            'key_skills': preferences.key_skills[:10],  # Limit for storage
            'requires_sponsorship': preferences.requires_sponsorship,
            'open_to_remote': preferences.open_to_remote,
            'preferred_industries': preferences.preferred_industries,
            'algorithm_version': self.algorithm_version
        }


# Convenience function for easy access
def generate_recommendations_for_user(user: User, limit: int = 10, refresh: bool = False) -> List[JobRecommendation]:
    """
    Convenience function to generate recommendations for a user
    """
    engine = JobRecommendationEngine()
    return engine.generate_recommendations(user, limit, refresh)