from rest_framework import serializers
from .models import UserJobPreference, JobRecommendation, RecommendationBatch
from jobs.serializers import JobListSerializer
from companies.serializers import CompanyListSerializer
from accounts.serializers import UserProfileSerializer


class UserJobPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for user job preferences"""
    
    class Meta:
        model = UserJobPreference
        fields = [
            'id', 'preferred_locations', 'max_commute_distance', 
            'open_to_remote', 'open_to_hybrid', 'preferred_job_types',
            'preferred_industries', 'experience_level', 'min_salary',
            'max_salary', 'salary_currency', 'key_skills', 'avoid_keywords',
            'preferred_company_sizes', 'avoid_companies', 'requires_sponsorship',
            'visa_types_needed', 'notification_frequency', 'max_recommendations',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_key_skills(self, value):
        """Validate and clean key skills"""
        if not isinstance(value, list):
            raise serializers.ValidationError("Key skills must be a list")
        
        # Clean and limit skills
        cleaned_skills = []
        for skill in value[:20]:  # Limit to 20 skills
            if isinstance(skill, str) and skill.strip():
                cleaned_skills.append(skill.strip().lower())
        
        return cleaned_skills
    
    def validate_preferred_locations(self, value):
        """Validate preferred locations"""
        if not isinstance(value, list):
            raise serializers.ValidationError("Preferred locations must be a list")
        
        return [loc.strip() for loc in value[:10] if isinstance(loc, str) and loc.strip()]


class JobRecommendationListSerializer(serializers.ModelSerializer):
    """Serializer for job recommendation list view"""
    job = JobListSerializer(read_only=True)
    match_score_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = JobRecommendation
        fields = [
            'id', 'job', 'match_score', 'match_score_percentage', 
            'match_reasons', 'viewed', 'clicked', 'applied',
            'created_at'
        ]
    
    def get_match_score_percentage(self, obj):
        """Convert match score to percentage"""
        return round(obj.match_score * 100, 1)


class JobRecommendationDetailSerializer(serializers.ModelSerializer):
    """Serializer for detailed job recommendation"""
    job = JobListSerializer(read_only=True)
    match_score_percentage = serializers.SerializerMethodField()
    score_breakdown = serializers.SerializerMethodField()
    
    class Meta:
        model = JobRecommendation
        fields = [
            'id', 'job', 'match_score', 'match_score_percentage',
            'score_breakdown', 'match_reasons', 'viewed', 'clicked',
            'applied', 'feedback', 'created_at'
        ]
    
    def get_match_score_percentage(self, obj):
        """Convert match score to percentage"""
        return round(obj.match_score * 100, 1)
    
    def get_score_breakdown(self, obj):
        """Get detailed score breakdown"""
        return {
            'skills': round(obj.skill_match_score * 100, 1),
            'location': round(obj.location_match_score * 100, 1),
            'salary': round(obj.salary_match_score * 100, 1),
            'company': round(obj.company_match_score * 100, 1),
            'experience': round(obj.experience_match_score * 100, 1)
        }


class RecommendationFeedbackSerializer(serializers.ModelSerializer):
    """Serializer for recommendation feedback"""
    
    class Meta:
        model = JobRecommendation
        fields = ['feedback', 'feedback_notes']
    
    def validate_feedback(self, value):
        """Validate feedback choice"""
        valid_choices = ['helpful', 'not_helpful', 'not_interested', 'already_applied']
        if value not in valid_choices:
            raise serializers.ValidationError(f"Invalid feedback choice. Must be one of: {valid_choices}")
        return value


class GenerateRecommendationsSerializer(serializers.Serializer):
    """Serializer for generating recommendations request"""
    limit = serializers.IntegerField(
        default=10,
        min_value=1,
        max_value=50,
        help_text="Number of recommendations to generate"
    )
    refresh = serializers.BooleanField(
        default=False,
        help_text="Whether to generate fresh recommendations"
    )