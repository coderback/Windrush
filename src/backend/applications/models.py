from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import FileExtensionValidator
from utils.file_handlers import get_file_url


def get_cv_upload_path(instance, filename):
    """Generate secure upload path for CV files"""
    from utils.file_handlers import SecureFileUploadHandler
    handler = SecureFileUploadHandler()
    secure_filename = handler.generate_secure_filename(filename, instance.applicant_id)
    return handler.get_upload_path(secure_filename, 'cv')


def get_cover_letter_upload_path(instance, filename):
    """Generate secure upload path for cover letter files"""
    from utils.file_handlers import SecureFileUploadHandler
    handler = SecureFileUploadHandler()
    secure_filename = handler.generate_secure_filename(filename, instance.applicant_id)
    return handler.get_upload_path(secure_filename, 'cover_letter')


def get_portfolio_upload_path(instance, filename):
    """Generate secure upload path for portfolio files"""
    from utils.file_handlers import SecureFileUploadHandler
    handler = SecureFileUploadHandler()
    secure_filename = handler.generate_secure_filename(filename, instance.applicant_id)
    return handler.get_upload_path(secure_filename, 'portfolio')


class Application(models.Model):
    """
    Job application model supporting both regular and speculative applications
    """
    APPLICATION_TYPE_CHOICES = (
        ('job_application', 'Job Application'),
        ('speculative', 'Speculative Application'),
    )
    
    STATUS_CHOICES = (
        ('submitted', 'Submitted'),
        ('reviewed', 'Under Review'),
        ('shortlisted', 'Shortlisted'),
        ('interview_scheduled', 'Interview Scheduled'),
        ('interviewing', 'Interviewing'),
        ('assessment', 'Assessment/Test Stage'),
        ('final_interview', 'Final Interview'),
        ('offer_made', 'Offer Made'),
        ('offer_accepted', 'Offer Accepted'),
        ('offer_declined', 'Offer Declined'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
        ('on_hold', 'On Hold'),
    )
    
    REJECTION_REASON_CHOICES = (
        ('qualifications', 'Insufficient Qualifications'),
        ('experience', 'Insufficient Experience'),
        ('skills', 'Skills Mismatch'),
        ('visa', 'Visa/Work Authorization Issues'),
        ('salary_expectations', 'Salary Expectations'),
        ('location', 'Location Constraints'),
        ('cultural_fit', 'Cultural Fit'),
        ('position_filled', 'Position Already Filled'),
        ('overqualified', 'Overqualified'),
        ('other', 'Other'),
    )
    
    # Core Application Information
    applicant = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='applications'
    )
    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='applications',
        null=True,
        blank=True,
        help_text="Job being applied for (null for speculative applications)"
    )
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='applications',
        help_text="Company being applied to"
    )
    
    application_type = models.CharField(
        max_length=20,
        choices=APPLICATION_TYPE_CHOICES,
        default='job_application'
    )
    
    # Application Content
    cover_letter = models.TextField(
        max_length=5000,
        help_text="Cover letter or application message"
    )
    additional_info = models.TextField(
        blank=True,
        max_length=2000,
        help_text="Additional information or notes"
    )
    
    # Documents
    cv_file = models.FileField(
        upload_to=get_cv_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'doc', 'docx'])],
        help_text="CV/Resume file"
    )
    cover_letter_file = models.FileField(
        upload_to=get_cover_letter_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'doc', 'docx'])],
        null=True,
        blank=True,
        help_text="Optional separate cover letter file"
    )
    portfolio_file = models.FileField(
        upload_to=get_portfolio_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'zip', 'rar'])],
        null=True,
        blank=True,
        help_text="Optional portfolio file"
    )
    
    # Application Status
    status = models.CharField(
        max_length=25,
        choices=STATUS_CHOICES,
        default='submitted'
    )
    rejection_reason = models.CharField(
        max_length=30,
        choices=REJECTION_REASON_CHOICES,
        null=True,
        blank=True
    )
    
    # Employer Feedback
    employer_notes = models.TextField(
        blank=True,
        max_length=2000,
        help_text="Internal notes from employer"
    )
    feedback_to_candidate = models.TextField(
        blank=True,
        max_length=1000,
        help_text="Feedback shared with candidate"
    )
    
    # Interview & Assessment Details
    interview_scheduled_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Scheduled interview date and time"
    )
    interview_location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Interview location or video call link"
    )
    interview_notes = models.TextField(
        blank=True,
        max_length=1000,
        help_text="Interview notes and feedback"
    )
    
    # Salary & Offer Details
    offered_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Salary offered to candidate"
    )
    offered_benefits = models.JSONField(
        default=list,
        help_text="Benefits offered with the position"
    )
    offer_expiry_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when offer expires"
    )
    start_date_offered = models.DateField(
        null=True,
        blank=True,
        help_text="Proposed start date"
    )
    
    # Visa Sponsorship Details
    requires_sponsorship = models.BooleanField(
        default=True,
        help_text="Does applicant require visa sponsorship?"
    )
    current_visa_status = models.CharField(
        max_length=100,
        blank=True,
        help_text="Applicant's current visa status"
    )
    visa_expiry_date = models.DateField(
        null=True,
        blank=True,
        help_text="Current visa expiry date"
    )
    
    # Application Tracking
    source = models.CharField(
        max_length=100,
        blank=True,
        help_text="How applicant found this opportunity"
    )
    referrer = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referrals',
        help_text="User who referred this applicant"
    )
    
    # Metadata
    applied_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    viewed_by_employer = models.BooleanField(
        default=False,
        help_text="Has employer viewed this application?"
    )
    viewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When employer first viewed application"
    )
    
    # Communication tracking
    last_contact_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last communication with candidate"
    )
    next_follow_up_date = models.DateField(
        null=True,
        blank=True,
        help_text="Next planned follow-up date"
    )
    
    class Meta:
        verbose_name = _('Application')
        verbose_name_plural = _('Applications')
        ordering = ['-applied_at']
        indexes = [
            models.Index(fields=['applicant', 'status']),
            models.Index(fields=['job', 'status']),
            models.Index(fields=['company', 'status']),
            models.Index(fields=['application_type']),
            models.Index(fields=['applied_at']),
            models.Index(fields=['status', 'applied_at']),
        ]
        
        # Constraints
        constraints = [
            models.CheckConstraint(
                check=models.Q(job__isnull=False) | models.Q(application_type='speculative'),
                name='job_required_for_job_applications'
            ),
        ]
    
    def __str__(self):
        if self.job:
            return f"{self.applicant.full_name} → {self.job.title} at {self.company.name}"
        return f"{self.applicant.full_name} → {self.company.name} (Speculative)"
    
    def save(self, *args, **kwargs):
        # Set company from job if not already set
        if self.job and not self.company_id:
            self.company = self.job.company
        
        # Set application type based on job presence
        if not self.job:
            self.application_type = 'speculative'
        else:
            self.application_type = 'job_application'
            
        super().save(*args, **kwargs)
    
    @property
    def is_active(self):
        """Check if application is still in active consideration"""
        active_statuses = [
            'submitted', 'reviewed', 'shortlisted', 'interview_scheduled',
            'interviewing', 'assessment', 'final_interview', 'offer_made'
        ]
        return self.status in active_statuses
    
    @property
    def is_successful(self):
        """Check if application was successful"""
        return self.status == 'offer_accepted'
    
    @property
    def is_rejected(self):
        """Check if application was rejected"""
        return self.status == 'rejected'
    
    @property
    def days_since_applied(self):
        """Calculate days since application was submitted"""
        from django.utils import timezone
        return (timezone.now() - self.applied_at).days
    
    @property
    def cv_file_url(self):
        """Get secure URL for CV file"""
        return get_file_url(self.cv_file.name) if self.cv_file else None
    
    @property
    def cover_letter_file_url(self):
        """Get secure URL for cover letter file"""
        return get_file_url(self.cover_letter_file.name) if self.cover_letter_file else None
    
    @property
    def portfolio_file_url(self):
        """Get secure URL for portfolio file"""
        return get_file_url(self.portfolio_file.name) if self.portfolio_file else None


class ApplicationStatusHistory(models.Model):
    """
    Track status changes for applications
    """
    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name='status_history'
    )
    from_status = models.CharField(
        max_length=25,
        choices=Application.STATUS_CHOICES,
        null=True,
        blank=True
    )
    to_status = models.CharField(
        max_length=25,
        choices=Application.STATUS_CHOICES
    )
    notes = models.TextField(
        blank=True,
        max_length=500,
        help_text="Notes about status change"
    )
    changed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('Application Status History')
        verbose_name_plural = _('Application Status Histories')
        ordering = ['-changed_at']
    
    def __str__(self):
        return f"{self.application} - {self.from_status} → {self.to_status}"


class ApplicationMessage(models.Model):
    """
    Messages between applicants and employers regarding applications
    """
    MESSAGE_TYPE_CHOICES = (
        ('system', 'System Generated'),
        ('employer_to_applicant', 'Employer to Applicant'),
        ('applicant_to_employer', 'Applicant to Employer'),
    )
    
    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    message_type = models.CharField(
        max_length=25,
        choices=MESSAGE_TYPE_CHOICES,
        default='employer_to_applicant'
    )
    sender = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )
    recipient = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='received_messages'
    )
    
    subject = models.CharField(max_length=200)
    message = models.TextField(max_length=2000)
    
    # Message Status
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Attachments
    attachment = models.FileField(
        upload_to='messages/attachments/%Y/%m/',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(
            allowed_extensions=['pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png']
        )]
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('Application Message')
        verbose_name_plural = _('Application Messages')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['application', 'created_at']),
            models.Index(fields=['recipient', 'is_read']),
        ]
    
    def __str__(self):
        return f"{self.subject} - {self.sender.full_name} to {self.recipient.full_name}"
    
    def mark_as_read(self):
        """Mark message as read"""
        if not self.is_read:
            self.is_read = True
            from django.utils import timezone
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])