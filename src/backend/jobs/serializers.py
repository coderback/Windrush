from rest_framework import serializers
from decimal import Decimal
from .models import Job, JobSavedByUser, JobAlert
from companies.serializers import CompanyListSerializer


class JobListSerializer(serializers.ModelSerializer):
    """Serializer for job list view (optimized for performance)"""
    company = CompanyListSerializer(read_only=True)
    salary_range_display = serializers.ReadOnlyField()
    offers_visa_sponsorship = serializers.ReadOnlyField()
    days_since_posted = serializers.ReadOnlyField()
    is_saved = serializers.SerializerMethodField()
    
    class Meta:
        model = Job
        fields = [
            'id', 'title', 'slug', 'company', 'job_type', 'experience_level',
            'location_city', 'location_region', 'remote_policy',
            'salary_min', 'salary_max', 'salary_range_display',
            'visa_sponsorship', 'offers_visa_sponsorship',
            'required_skills', 'is_featured', 'is_urgent',
            'view_count', 'application_count', 'days_since_posted',
            'is_saved', 'created_at', 'application_deadline'
        ]
    
    def get_is_saved(self, obj):
        """Check if current user has saved this job"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return JobSavedByUser.objects.filter(
                user=request.user, job=obj
            ).exists()
        return False


class JobDetailSerializer(serializers.ModelSerializer):
    """Serializer for job detail view"""
    company = CompanyListSerializer(read_only=True)
    salary_range_display = serializers.ReadOnlyField()
    offers_visa_sponsorship = serializers.ReadOnlyField()
    days_since_posted = serializers.ReadOnlyField()
    is_saved = serializers.SerializerMethodField()
    has_applied = serializers.SerializerMethodField()
    
    class Meta:
        model = Job
        fields = [
            'id', 'title', 'slug', 'company', 'description', 'responsibilities',
            'requirements', 'nice_to_have', 'job_type', 'experience_level',
            'industry', 'department', 'location_city', 'location_region',
            'location_country', 'postcode', 'remote_policy', 'remote_details',
            'salary_min', 'salary_max', 'salary_currency', 'salary_period',
            'salary_negotiable', 'salary_range_display', 'benefits',
            'visa_sponsorship', 'offers_visa_sponsorship', 'sponsored_visa_types',
            'sponsorship_details', 'minimum_visa_salary', 'required_skills',
            'preferred_skills', 'technologies', 'education_level', 'degree_subjects',
            'application_deadline', 'start_date', 'application_url',
            'application_instructions', 'is_featured', 'is_urgent', 'is_premium',
            'view_count', 'application_count', 'days_since_posted',
            'is_saved', 'has_applied', 'created_at', 'updated_at'
        ]
    
    def get_is_saved(self, obj):
        """Check if current user has saved this job"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return JobSavedByUser.objects.filter(
                user=request.user, job=obj
            ).exists()
        return False
    
    def get_has_applied(self, obj):
        """Check if current user has applied to this job"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.applications.filter(applicant=request.user).exists()
        return False


class JobCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating jobs"""
    
    class Meta:
        model = Job
        fields = [
            'title', 'company', 'description', 'responsibilities',
            'requirements', 'nice_to_have', 'job_type', 'experience_level',
            'industry', 'department', 'location_city', 'location_region',
            'postcode', 'remote_policy', 'remote_details',
            'salary_min', 'salary_max', 'salary_period', 'salary_negotiable',
            'benefits', 'visa_sponsorship', 'sponsored_visa_types',
            'sponsorship_details', 'minimum_visa_salary', 'required_skills',
            'preferred_skills', 'technologies', 'education_level', 'degree_subjects',
            'application_deadline', 'start_date', 'application_url',
            'application_instructions', 'is_featured', 'is_urgent'
        ]
    
    def validate_salary_min(self, value):
        """Validate minimum salary"""
        if value and value < Decimal('0.01'):
            raise serializers.ValidationError("Minimum salary must be positive")
        return value
    
    def validate_salary_max(self, value):
        """Validate maximum salary"""
        if value and value < Decimal('0.01'):
            raise serializers.ValidationError("Maximum salary must be positive")
        return value
    
    def validate(self, attrs):
        """Cross-field validation"""
        salary_min = attrs.get('salary_min')
        salary_max = attrs.get('salary_max')
        
        if salary_min and salary_max and salary_min > salary_max:
            raise serializers.ValidationError(
                "Minimum salary cannot be greater than maximum salary"
            )
        
        # Validate visa sponsorship details
        visa_sponsorship = attrs.get('visa_sponsorship')
        sponsored_visa_types = attrs.get('sponsored_visa_types', [])
        
        if visa_sponsorship in ['available', 'considered'] and not sponsored_visa_types:
            raise serializers.ValidationError(
                "Please specify which visa types can be sponsored"
            )
        
        # Validate minimum visa salary against job salary
        minimum_visa_salary = attrs.get('minimum_visa_salary')
        if minimum_visa_salary and salary_min and minimum_visa_salary < salary_min:
            raise serializers.ValidationError(
                "Minimum visa salary cannot be less than job minimum salary"
            )
        
        return attrs
    
    def create(self, validated_data):
        """Set posted_by to current user"""
        validated_data['posted_by'] = self.context['request'].user
        validated_data['status'] = 'active'  # Auto-activate for now
        return super().create(validated_data)


class JobSearchSerializer(serializers.Serializer):
    """Serializer for job search parameters"""
    search = serializers.CharField(required=False, max_length=255)
    location = serializers.CharField(required=False, max_length=100)
    job_type = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False
    )
    experience_level = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False
    )
    industry = serializers.CharField(required=False, max_length=100)
    remote_policy = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False
    )
    salary_min = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )
    salary_max = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )
    visa_sponsorship = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False
    )
    required_skills = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False
    )
    company = serializers.CharField(required=False, max_length=255)
    posted_since = serializers.IntegerField(required=False, min_value=1)
    is_featured = serializers.BooleanField(required=False)
    is_urgent = serializers.BooleanField(required=False)
    ordering = serializers.CharField(required=False, default='-created_at')
    
    def validate_ordering(self, value):
        """Validate ordering field"""
        valid_fields = [
            'created_at', '-created_at', 'title', '-title',
            'salary_min', '-salary_min', 'salary_max', '-salary_max',
            'application_deadline', '-application_deadline',
            'view_count', '-view_count', 'application_count', '-application_count'
        ]
        if value not in valid_fields:
            raise serializers.ValidationError(
                f"Invalid ordering field. Choose from: {', '.join(valid_fields)}"
            )
        return value


class JobSavedByUserSerializer(serializers.ModelSerializer):
    """Serializer for saved jobs"""
    job = JobListSerializer(read_only=True)
    
    class Meta:
        model = JobSavedByUser
        fields = ['id', 'job', 'saved_at', 'notes']
        read_only_fields = ['id', 'saved_at']


class JobSaveSerializer(serializers.ModelSerializer):
    """Serializer for saving/unsaving jobs"""
    
    class Meta:
        model = JobSavedByUser
        fields = ['job', 'notes']
    
    def validate_job(self, value):
        """Ensure job exists and is active"""
        if value.status != 'active':
            raise serializers.ValidationError("Cannot save inactive job")
        return value
    
    def create(self, validated_data):
        """Create saved job for current user"""
        user = self.context['request'].user
        job = validated_data['job']
        
        # Check if already saved
        saved_job, created = JobSavedByUser.objects.get_or_create(
            user=user,
            job=job,
            defaults=validated_data
        )
        
        if not created:
            # Update notes if job was already saved
            saved_job.notes = validated_data.get('notes', saved_job.notes)
            saved_job.save()
        
        return saved_job


class JobAlertSerializer(serializers.ModelSerializer):
    """Serializer for job alerts"""
    matching_jobs_count = serializers.SerializerMethodField()
    
    class Meta:
        model = JobAlert
        fields = [
            'id', 'title', 'keywords', 'location_city', 'location_region',
            'job_types', 'experience_levels', 'industries', 'salary_min',
            'visa_sponsorship_required', 'is_active', 'frequency',
            'matching_jobs_count', 'created_at', 'last_sent'
        ]
        read_only_fields = ['id', 'created_at', 'last_sent', 'matching_jobs_count']
    
    def get_matching_jobs_count(self, obj):
        """Get count of jobs matching this alert"""
        # This would be implemented with actual job matching logic
        return 0  # Placeholder
    
    def create(self, validated_data):
        """Create job alert for current user"""
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class JobAlertCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating job alerts"""
    
    class Meta:
        model = JobAlert
        fields = [
            'title', 'keywords', 'location_city', 'location_region',
            'job_types', 'experience_levels', 'industries', 'salary_min',
            'visa_sponsorship_required', 'is_active', 'frequency'
        ]
    
    def validate_title(self, value):
        """Ensure alert title is unique for user"""
        user = self.context['request'].user
        instance = getattr(self, 'instance', None)
        
        if JobAlert.objects.filter(
            user=user, title__iexact=value
        ).exclude(id=instance.id if instance else None).exists():
            raise serializers.ValidationError(
                "You already have a job alert with this title"
            )
        
        return value
    
    def validate_salary_min(self, value):
        """Validate minimum salary"""
        if value and value < Decimal('0.01'):
            raise serializers.ValidationError("Minimum salary must be positive")
        return value