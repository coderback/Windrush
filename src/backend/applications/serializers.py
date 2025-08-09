from rest_framework import serializers
from django.core.files.uploadedfile import UploadedFile
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Application, ApplicationStatusHistory, ApplicationMessage
from jobs.serializers import JobListSerializer
from companies.serializers import CompanyListSerializer
from accounts.serializers import UserProfileSerializer
from utils.file_handlers import SecureFileUploadHandler


class ApplicationListSerializer(serializers.ModelSerializer):
    """Serializer for application list view"""
    job = JobListSerializer(read_only=True)
    company = CompanyListSerializer(read_only=True)
    days_since_applied = serializers.ReadOnlyField()
    is_active = serializers.ReadOnlyField()
    
    class Meta:
        model = Application
        fields = [
            'id', 'job', 'company', 'application_type', 'status',
            'applied_at', 'days_since_applied', 'is_active',
            'requires_sponsorship', 'current_visa_status'
        ]


class ApplicationDetailSerializer(serializers.ModelSerializer):
    """Serializer for application detail view"""
    job = JobListSerializer(read_only=True)
    company = CompanyListSerializer(read_only=True)
    applicant = UserProfileSerializer(read_only=True)
    days_since_applied = serializers.ReadOnlyField()
    is_active = serializers.ReadOnlyField()
    is_successful = serializers.ReadOnlyField()
    is_rejected = serializers.ReadOnlyField()
    
    class Meta:
        model = Application
        fields = [
            'id', 'applicant', 'job', 'company', 'application_type',
            'cover_letter', 'additional_info', 'cv_file', 'cover_letter_file',
            'portfolio_file', 'status', 'rejection_reason', 'employer_notes',
            'feedback_to_candidate', 'interview_scheduled_date', 'interview_location',
            'interview_notes', 'offered_salary', 'offered_benefits',
            'offer_expiry_date', 'start_date_offered', 'requires_sponsorship',
            'current_visa_status', 'visa_expiry_date', 'source', 'applied_at',
            'updated_at', 'viewed_by_employer', 'viewed_at', 'last_contact_date',
            'next_follow_up_date', 'days_since_applied', 'is_active',
            'is_successful', 'is_rejected'
        ]


class ApplicationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating job applications"""
    
    class Meta:
        model = Application
        fields = [
            'job', 'company', 'cover_letter', 'additional_info',
            'cv_file', 'cover_letter_file', 'portfolio_file',
            'requires_sponsorship', 'current_visa_status', 'visa_expiry_date',
            'source'
        ]
    
    def validate_cv_file(self, value):
        """Validate CV file using secure file handler"""
        if not value:
            raise serializers.ValidationError("CV file is required")
        
        try:
            handler = SecureFileUploadHandler()
            handler.validate_file(value, 'cv')
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
        
        return value
    
    def validate_cover_letter(self, value):
        """Validate cover letter content"""
        if not value or len(value.strip()) < 50:
            raise serializers.ValidationError(
                "Cover letter must be at least 50 characters long"
            )
        return value
    
    def validate(self, attrs):
        """Cross-field validation"""
        job = attrs.get('job')
        company = attrs.get('company')
        
        # For job applications, company must match job's company
        if job and company and job.company != company:
            raise serializers.ValidationError(
                "Company must match the job's company"
            )
        
        # For speculative applications, job should be None
        if not job and not company:
            raise serializers.ValidationError(
                "Either job or company must be specified"
            )
        
        # Check if user has already applied to this job
        user = self.context['request'].user
        if job and Application.objects.filter(applicant=user, job=job).exists():
            raise serializers.ValidationError(
                "You have already applied to this job"
            )
        
        return attrs
    
    def create(self, validated_data):
        """Create application with current user as applicant"""
        validated_data['applicant'] = self.context['request'].user
        return super().create(validated_data)


class SpeculativeApplicationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating speculative applications"""
    
    class Meta:
        model = Application
        fields = [
            'company', 'cover_letter', 'additional_info',
            'cv_file', 'cover_letter_file', 'portfolio_file',
            'requires_sponsorship', 'current_visa_status', 'visa_expiry_date',
            'source'
        ]
    
    def validate_cv_file(self, value):
        """Validate CV file using secure file handler"""
        if not value:
            raise serializers.ValidationError("CV file is required")
        
        try:
            handler = SecureFileUploadHandler()
            handler.validate_file(value, 'cv')
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
        
        return value
    
    def validate_cover_letter(self, value):
        """Validate cover letter content"""
        if not value or len(value.strip()) < 100:
            raise serializers.ValidationError(
                "Cover letter for speculative applications must be at least 100 characters long"
            )
        return value
    
    def validate(self, attrs):
        """Check if user has already sent speculative application to this company"""
        user = self.context['request'].user
        company = attrs['company']
        
        if Application.objects.filter(
            applicant=user, 
            company=company, 
            application_type='speculative'
        ).exists():
            raise serializers.ValidationError(
                "You have already sent a speculative application to this company"
            )
        
        return attrs
    
    def create(self, validated_data):
        """Create speculative application with current user as applicant"""
        validated_data['applicant'] = self.context['request'].user
        validated_data['job'] = None  # Speculative applications have no specific job
        return super().create(validated_data)


class ApplicationStatusUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating application status (employer use)"""
    notes = serializers.CharField(
        required=False, 
        max_length=500, 
        help_text="Optional notes about status change"
    )
    
    class Meta:
        model = Application
        fields = [
            'status', 'rejection_reason', 'employer_notes',
            'feedback_to_candidate', 'interview_scheduled_date',
            'interview_location', 'interview_notes', 'offered_salary',
            'offered_benefits', 'offer_expiry_date', 'start_date_offered',
            'next_follow_up_date', 'notes'
        ]
    
    def validate(self, attrs):
        """Validate status updates"""
        status = attrs.get('status')
        rejection_reason = attrs.get('rejection_reason')
        
        # If status is rejected, rejection reason is required
        if status == 'rejected' and not rejection_reason:
            raise serializers.ValidationError(
                "Rejection reason is required when rejecting an application"
            )
        
        # Clear rejection reason if not rejected
        if status != 'rejected':
            attrs['rejection_reason'] = None
        
        return attrs
    
    def update(self, instance, validated_data):
        """Update application status and create history record"""
        notes = validated_data.pop('notes', None)
        old_status = instance.status
        new_status = validated_data.get('status', old_status)
        
        # Update the application
        instance = super().update(instance, validated_data)
        
        # Create status history record if status changed
        if old_status != new_status:
            ApplicationStatusHistory.objects.create(
                application=instance,
                from_status=old_status,
                to_status=new_status,
                notes=notes or f"Status changed from {old_status} to {new_status}",
                changed_by=self.context['request'].user
            )
        
        return instance


class ApplicationStatusHistorySerializer(serializers.ModelSerializer):
    """Serializer for application status history"""
    changed_by = UserProfileSerializer(read_only=True)
    
    class Meta:
        model = ApplicationStatusHistory
        fields = [
            'id', 'from_status', 'to_status', 'notes',
            'changed_by', 'changed_at'
        ]


class ApplicationMessageSerializer(serializers.ModelSerializer):
    """Serializer for application messages"""
    sender = UserProfileSerializer(read_only=True)
    recipient = UserProfileSerializer(read_only=True)
    
    class Meta:
        model = ApplicationMessage
        fields = [
            'id', 'application', 'message_type', 'sender', 'recipient',
            'subject', 'message', 'is_read', 'read_at', 'attachment',
            'created_at'
        ]
        read_only_fields = ['id', 'is_read', 'read_at', 'created_at']


class ApplicationMessageCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating application messages"""
    recipient_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = ApplicationMessage
        fields = [
            'application', 'subject', 'message', 'attachment', 'recipient_id'
        ]
    
    def validate_recipient_id(self, value):
        """Validate recipient exists"""
        from accounts.models import User
        try:
            recipient = User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("Recipient not found")
        
        return value
    
    def validate(self, attrs):
        """Validate message permissions"""
        sender = self.context['request'].user
        application = attrs['application']
        recipient_id = attrs['recipient_id']
        
        # Check if sender is involved in this application
        if sender != application.applicant and not (
            sender.user_type == 'employer' and 
            application.company.created_by == sender
        ):
            raise serializers.ValidationError(
                "You don't have permission to message about this application"
            )
        
        # Set message type based on sender
        if sender == application.applicant:
            attrs['message_type'] = 'applicant_to_employer'
        else:
            attrs['message_type'] = 'employer_to_applicant'
        
        return attrs
    
    def create(self, validated_data):
        """Create message with sender and recipient"""
        from accounts.models import User
        
        recipient_id = validated_data.pop('recipient_id')
        recipient = User.objects.get(id=recipient_id)
        
        validated_data['sender'] = self.context['request'].user
        validated_data['recipient'] = recipient
        
        return super().create(validated_data)


class ApplicationSearchSerializer(serializers.Serializer):
    """Serializer for application search parameters"""
    status = serializers.ListField(
        child=serializers.CharField(max_length=25),
        required=False
    )
    application_type = serializers.CharField(required=False, max_length=20)
    company = serializers.CharField(required=False, max_length=255)
    job_title = serializers.CharField(required=False, max_length=200)
    applied_since = serializers.DateField(required=False)
    applied_until = serializers.DateField(required=False)
    requires_sponsorship = serializers.BooleanField(required=False)
    ordering = serializers.CharField(required=False, default='-applied_at')
    
    def validate_ordering(self, value):
        """Validate ordering field"""
        valid_fields = [
            'applied_at', '-applied_at', 'updated_at', '-updated_at',
            'status', '-status', 'company__name', '-company__name'
        ]
        if value not in valid_fields:
            raise serializers.ValidationError(
                f"Invalid ordering field. Choose from: {', '.join(valid_fields)}"
            )
        return value


class ApplicationStatsSerializer(serializers.Serializer):
    """Serializer for application statistics"""
    total_applications = serializers.IntegerField()
    job_applications = serializers.IntegerField()
    speculative_applications = serializers.IntegerField()
    active_applications = serializers.IntegerField()
    successful_applications = serializers.IntegerField()
    rejected_applications = serializers.IntegerField()
    by_status = serializers.DictField()
    by_month = serializers.DictField()