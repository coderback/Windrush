from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


def get_cv_upload_path(instance, filename):
    """Generate secure upload path for user CV files"""
    try:
        from utils.file_handlers import SecureFileUploadHandler
        handler = SecureFileUploadHandler()
        secure_filename = handler.generate_secure_filename(filename, instance.user_id)
        return handler.get_upload_path(secure_filename, 'cv')
    except ImportError:
        # Fallback to simple path generation
        import uuid
        from datetime import datetime
        date_path = datetime.now().strftime('%Y/%m')
        secure_name = str(uuid.uuid4())
        return f"uploads/cv/{date_path}/user_{instance.user_id}_{secure_name}_{filename}"


class User(AbstractUser):
    """
    Custom User model for Windrush platform
    Extends Django's AbstractUser with additional fields
    """
    USER_TYPES = (
        ('job_seeker', 'Job Seeker'),
        ('employer', 'Employer'),
        ('admin', 'Admin'),
    )
    
    email = models.EmailField(_('email address'), unique=True)
    user_type = models.CharField(
        max_length=20, 
        choices=USER_TYPES, 
        default='job_seeker',
        help_text='Type of user account'
    )
    is_verified = models.BooleanField(
        default=False,
        help_text='Whether the user has verified their email address'
    )
    is_premium = models.BooleanField(
        default=False,
        help_text='Whether the user has a premium subscription'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Use email as the username field
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']
    
    class Meta:
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        
    def __str__(self):
        return f"{self.email} ({self.get_user_type_display()})"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class JobSeekerProfile(models.Model):
    """
    Extended profile information for job seekers
    """
    VISA_STATUS_CHOICES = (
        ('student', 'Student Visa'),
        ('graduate', 'Graduate Visa'),
        ('skilled_worker', 'Skilled Worker Visa'),
        ('other', 'Other'),
        ('need_sponsorship', 'Need Sponsorship'),
    )
    
    JOB_TYPE_PREFERENCES = (
        ('internship', 'Internship'),
        ('placement', 'Placement Year'),
        ('graduate_scheme', 'Graduate Scheme'),
        ('full_time', 'Full Time'),
        ('part_time', 'Part Time'),
    )
    
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='job_seeker_profile'
    )
    
    # Personal Information
    phone_number = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    
    # Visa Information
    visa_status = models.CharField(
        max_length=20,
        choices=VISA_STATUS_CHOICES,
        default='need_sponsorship'
    )
    visa_expiry_date = models.DateField(null=True, blank=True)
    
    # Education & Experience
    education_level = models.CharField(max_length=200, blank=True)
    field_of_study = models.CharField(max_length=200, blank=True)
    university = models.CharField(max_length=200, blank=True)
    graduation_year = models.IntegerField(null=True, blank=True)
    years_of_experience = models.IntegerField(default=0)
    
    # Job Preferences
    job_type_preferences = models.JSONField(
        default=list,
        help_text='List of preferred job types'
    )
    preferred_locations = models.JSONField(
        default=list,
        help_text='List of preferred work locations'
    )
    preferred_industries = models.JSONField(
        default=list,
        help_text='List of preferred industries'
    )
    expected_salary_min = models.IntegerField(null=True, blank=True)
    expected_salary_max = models.IntegerField(null=True, blank=True)
    
    # Skills & Bio
    skills = models.JSONField(
        default=list,
        help_text='List of skills'
    )
    bio = models.TextField(blank=True, max_length=1000)
    
    # Profile Settings
    is_profile_public = models.BooleanField(
        default=False,
        help_text='Allow employers to find this profile'
    )
    is_available_for_work = models.BooleanField(default=True)
    
    # CV/Resume files
    primary_cv = models.FileField(
        upload_to=get_cv_upload_path,
        null=True,
        blank=True,
        help_text='Primary CV file'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Job Seeker Profile')
        verbose_name_plural = _('Job Seeker Profiles')
        
    def __str__(self):
        return f"{self.user.full_name} - Job Seeker Profile"
    
    @property
    def primary_cv_url(self):
        """Get secure URL for primary CV file"""
        if not self.primary_cv:
            return None
        try:
            from utils.file_handlers import get_file_url
            return get_file_url(self.primary_cv.name)
        except ImportError:
            # Fallback to default storage URL
            from django.core.files.storage import default_storage
            return default_storage.url(self.primary_cv.name)