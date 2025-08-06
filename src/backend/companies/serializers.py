from rest_framework import serializers
from .models import Company, CompanyReview


class CompanyListSerializer(serializers.ModelSerializer):
    """Serializer for company list view (limited fields)"""
    active_jobs_count = serializers.ReadOnlyField()
    can_sponsor_skilled_worker = serializers.ReadOnlyField()
    
    class Meta:
        model = Company
        fields = [
            'id', 'name', 'slug', 'industry', 'company_size',
            'city', 'region', 'logo', 'is_sponsor', 'sponsor_status',
            'sponsor_types', 'active_jobs_count', 'can_sponsor_skilled_worker',
            'is_featured', 'is_premium_partner'
        ]


class CompanyDetailSerializer(serializers.ModelSerializer):
    """Serializer for company detail view"""
    active_jobs_count = serializers.ReadOnlyField()
    can_sponsor_skilled_worker = serializers.ReadOnlyField()
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Company
        fields = [
            'id', 'name', 'slug', 'website', 'email', 'phone',
            'description', 'industry', 'company_size', 'founded_year',
            'headquarters_address', 'city', 'region', 'country', 'postcode',
            'is_sponsor', 'sponsor_license_number', 'sponsor_status',
            'sponsor_types', 'sponsor_verified_date',
            'logo', 'banner_image', 'benefits', 'company_values',
            'linkedin_url', 'twitter_url', 'glassdoor_url',
            'is_featured', 'is_premium_partner',
            'total_jobs_posted', 'total_hires_made',
            'active_jobs_count', 'can_sponsor_skilled_worker',
            'average_rating', 'review_count',
            'created_at', 'updated_at'
        ]
    
    def get_average_rating(self, obj):
        """Calculate average rating from reviews"""
        reviews = obj.reviews.filter(is_approved=True)
        if reviews.exists():
            return round(sum(r.overall_rating for r in reviews) / reviews.count(), 1)
        return None
    
    def get_review_count(self, obj):
        """Get count of approved reviews"""
        return obj.reviews.filter(is_approved=True).count()


class CompanyCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating company"""
    
    class Meta:
        model = Company
        fields = [
            'name', 'website', 'email', 'phone', 'description',
            'industry', 'company_size', 'founded_year',
            'headquarters_address', 'city', 'region', 'postcode',
            'sponsor_license_number', 'sponsor_types',
            'logo', 'banner_image', 'benefits', 'company_values',
            'linkedin_url', 'twitter_url', 'glassdoor_url'
        ]
    
    def validate_name(self, value):
        """Ensure company name is unique (case-insensitive)"""
        instance = getattr(self, 'instance', None)
        if Company.objects.filter(name__iexact=value).exclude(id=instance.id if instance else None).exists():
            raise serializers.ValidationError("A company with this name already exists")
        return value
    
    def validate_sponsor_license_number(self, value):
        """Validate sponsor license number format and uniqueness"""
        if value:
            # Remove spaces and convert to uppercase
            value = value.replace(' ', '').upper()
            
            # Basic format validation (adjust based on actual UK format)
            if len(value) < 8 or len(value) > 15:
                raise serializers.ValidationError(
                    "Sponsor license number must be between 8 and 15 characters"
                )
            
            # Check uniqueness
            instance = getattr(self, 'instance', None)
            if Company.objects.filter(
                sponsor_license_number=value
            ).exclude(id=instance.id if instance else None).exists():
                raise serializers.ValidationError(
                    "A company with this sponsor license number already exists"
                )
        
        return value
    
    def validate_founded_year(self, value):
        """Validate founded year"""
        if value:
            import datetime
            current_year = datetime.datetime.now().year
            if value < 1800 or value > current_year:
                raise serializers.ValidationError(
                    f"Founded year must be between 1800 and {current_year}"
                )
        return value


class CompanyReviewSerializer(serializers.ModelSerializer):
    """Serializer for company reviews"""
    reviewer_name = serializers.SerializerMethodField()
    reviewer_is_anonymous = serializers.BooleanField(source='is_anonymous', read_only=True)
    
    class Meta:
        model = CompanyReview
        fields = [
            'id', 'company', 'reviewer_name', 'reviewer_is_anonymous',
            'title', 'review_text', 'overall_rating',
            'work_life_balance', 'compensation', 'career_opportunities',
            'management', 'culture', 'job_title', 'employment_status',
            'employment_length', 'received_sponsorship', 'sponsorship_experience',
            'helpful_count', 'created_at'
        ]
        read_only_fields = ['id', 'helpful_count', 'created_at']
    
    def get_reviewer_name(self, obj):
        """Return reviewer name or 'Anonymous' based on anonymity setting"""
        if obj.is_anonymous:
            return "Anonymous"
        return obj.reviewer.full_name or f"User {obj.reviewer.id}"


class CompanyReviewCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating company reviews"""
    
    class Meta:
        model = CompanyReview
        fields = [
            'company', 'title', 'review_text', 'overall_rating',
            'work_life_balance', 'compensation', 'career_opportunities',
            'management', 'culture', 'job_title', 'employment_status',
            'employment_length', 'received_sponsorship', 'sponsorship_experience',
            'is_anonymous'
        ]
    
    def validate_overall_rating(self, value):
        """Validate overall rating is between 1 and 5"""
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value
    
    def validate(self, attrs):
        """Ensure user hasn't already reviewed this company"""
        user = self.context['request'].user
        company = attrs['company']
        
        if CompanyReview.objects.filter(company=company, reviewer=user).exists():
            raise serializers.ValidationError(
                "You have already reviewed this company"
            )
        
        return attrs
    
    def create(self, validated_data):
        """Create review with current user as reviewer"""
        validated_data['reviewer'] = self.context['request'].user
        return super().create(validated_data)


class CompanySearchSerializer(serializers.Serializer):
    """Serializer for company search parameters"""
    search = serializers.CharField(required=False, max_length=255)
    industry = serializers.CharField(required=False, max_length=100)
    location = serializers.CharField(required=False, max_length=100)
    company_size = serializers.CharField(required=False, max_length=20)
    sponsor_status = serializers.CharField(required=False, max_length=20)
    visa_types = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False
    )
    has_active_jobs = serializers.BooleanField(required=False)
    is_featured = serializers.BooleanField(required=False)
    ordering = serializers.CharField(
        required=False,
        default='name'
    )
    
    def validate_ordering(self, value):
        """Validate ordering field"""
        valid_fields = [
            'name', '-name', 'created_at', '-created_at',
            'total_jobs_posted', '-total_jobs_posted',
            'city', '-city', 'industry', '-industry'
        ]
        if value not in valid_fields:
            raise serializers.ValidationError(
                f"Invalid ordering field. Choose from: {', '.join(valid_fields)}"
            )
        return value