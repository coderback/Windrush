from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from django.urls import reverse
from decimal import Decimal


class Job(models.Model):
    """
    Job posting model with visa sponsorship focus
    """
    JOB_TYPE_CHOICES = (
        ('full_time', 'Full Time'),
        ('part_time', 'Part Time'),
        ('contract', 'Contract'),
        ('internship', 'Internship'),
        ('placement', 'Placement Year'),
        ('graduate_scheme', 'Graduate Scheme'),
        ('apprenticeship', 'Apprenticeship'),
    )
    
    EXPERIENCE_LEVEL_CHOICES = (
        ('entry', 'Entry Level (0-2 years)'),
        ('junior', 'Junior (1-3 years)'),
        ('mid', 'Mid Level (3-5 years)'),
        ('senior', 'Senior (5+ years)'),
        ('lead', 'Lead/Principal (7+ years)'),
        ('manager', 'Manager'),
        ('director', 'Director/VP'),
    )
    
    REMOTE_POLICY_CHOICES = (
        ('office', 'On-site'),
        ('remote', 'Fully Remote'),
        ('hybrid', 'Hybrid'),
        ('flexible', 'Flexible'),
    )
    
    VISA_SPONSORSHIP_CHOICES = (
        ('available', 'Visa Sponsorship Available'),
        ('considered', 'Sponsorship Considered'),
        ('not_available', 'No Sponsorship'),
        ('existing_only', 'Existing Visa Holders Only'),
    )
    
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('filled', 'Filled'),
        ('expired', 'Expired'),
        ('closed', 'Closed'),
    )
    
    # Basic Job Information
    title = models.CharField(
        max_length=200,
        help_text="Job title/position name"
    )
    slug = models.SlugField(
        max_length=255,
        unique=True,
        help_text="URL-friendly job identifier"
    )
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='jobs'
    )
    
    # Job Details
    description = models.TextField(
        help_text="Full job description and requirements"
    )
    responsibilities = models.TextField(
        blank=True,
        help_text="Key responsibilities and duties"
    )
    requirements = models.TextField(
        blank=True,
        help_text="Required qualifications and skills"
    )
    nice_to_have = models.TextField(
        blank=True,
        help_text="Preferred/nice-to-have qualifications"
    )
    
    # Job Classification
    job_type = models.CharField(
        max_length=20,
        choices=JOB_TYPE_CHOICES,
        default='full_time'
    )
    experience_level = models.CharField(
        max_length=20,
        choices=EXPERIENCE_LEVEL_CHOICES,
        default='entry'
    )
    industry = models.CharField(
        max_length=100,
        blank=True,
        help_text="Job industry/sector"
    )
    department = models.CharField(
        max_length=100,
        blank=True,
        help_text="Department or team"
    )
    
    # Location Information
    location_city = models.CharField(
        max_length=100,
        help_text="Primary work location city"
    )
    location_region = models.CharField(
        max_length=100,
        blank=True,
        help_text="State/region/county"
    )
    location_country = models.CharField(
        max_length=100,
        default='United Kingdom'
    )
    postcode = models.CharField(max_length=10, blank=True)
    
    # Remote Work Policy
    remote_policy = models.CharField(
        max_length=20,
        choices=REMOTE_POLICY_CHOICES,
        default='office'
    )
    remote_details = models.TextField(
        blank=True,
        max_length=500,
        help_text="Details about remote work arrangements"
    )
    
    # Salary Information
    salary_min = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Minimum salary in GBP"
    )
    salary_max = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Maximum salary in GBP"
    )
    salary_currency = models.CharField(
        max_length=3,
        default='GBP',
        help_text="Salary currency code"
    )
    salary_period = models.CharField(
        max_length=20,
        choices=(
            ('hourly', 'Per Hour'),
            ('daily', 'Per Day'),
            ('weekly', 'Per Week'),
            ('monthly', 'Per Month'),
            ('yearly', 'Per Year'),
        ),
        default='yearly'
    )
    salary_negotiable = models.BooleanField(default=False)
    
    # Benefits & Perks
    benefits = models.JSONField(
        default=list,
        help_text="List of benefits and perks"
    )
    
    # Visa Sponsorship - Core Feature
    visa_sponsorship = models.CharField(
        max_length=20,
        choices=VISA_SPONSORSHIP_CHOICES,
        default='available',
        help_text="Visa sponsorship availability"
    )
    sponsored_visa_types = models.JSONField(
        default=list,
        help_text="Types of visas this job can sponsor"
    )
    sponsorship_details = models.TextField(
        blank=True,
        max_length=1000,
        help_text="Additional details about visa sponsorship process"
    )
    minimum_visa_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Minimum salary required for visa sponsorship"
    )
    
    # Skills & Tags
    required_skills = models.JSONField(
        default=list,
        help_text="List of required skills"
    )
    preferred_skills = models.JSONField(
        default=list,
        help_text="List of preferred skills"
    )
    technologies = models.JSONField(
        default=list,
        help_text="Technologies and tools used"
    )
    
    # Education Requirements
    education_level = models.CharField(
        max_length=100,
        blank=True,
        help_text="Required education level"
    )
    degree_subjects = models.JSONField(
        default=list,
        help_text="Relevant degree subjects"
    )
    
    # Application Details
    application_deadline = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Application deadline"
    )
    start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Expected start date"
    )
    application_url = models.URLField(
        blank=True,
        null=True,
        help_text="External application URL"
    )
    application_instructions = models.TextField(
        blank=True,
        max_length=1000,
        help_text="Special application instructions"
    )
    
    # Job Status & Management
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )
    is_featured = models.BooleanField(
        default=False,
        help_text="Feature this job prominently"
    )
    is_urgent = models.BooleanField(
        default=False,
        help_text="Mark as urgent hiring"
    )
    is_premium = models.BooleanField(
        default=False,
        help_text="Premium job posting"
    )
    
    # Statistics
    view_count = models.IntegerField(default=0)
    application_count = models.IntegerField(default=0)
    
    # Metadata
    posted_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='jobs_posted'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this job posting expires"
    )
    
    class Meta:
        verbose_name = _('Job')
        verbose_name_plural = _('Jobs')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['job_type']),
            models.Index(fields=['location_city']),
            models.Index(fields=['experience_level']),
            models.Index(fields=['visa_sponsorship']),
            models.Index(fields=['salary_min', 'salary_max']),
            models.Index(fields=['created_at']),
            models.Index(fields=['is_featured', 'status']),
        ]
    
    def __str__(self):
        return f"{self.title} at {self.company.name}"
    
    def get_absolute_url(self):
        return reverse('job_detail', kwargs={'slug': self.slug})
    
    @property
    def is_active(self):
        """Check if job is currently active and accepting applications"""
        return self.status == 'active'
    
    @property
    def salary_range_display(self):
        """Display salary range in a readable format"""
        if self.salary_min and self.salary_max:
            return f"£{self.salary_min:,.0f} - £{self.salary_max:,.0f} {self.salary_period}"
        elif self.salary_min:
            return f"£{self.salary_min:,.0f}+ {self.salary_period}"
        elif self.salary_max:
            return f"Up to £{self.salary_max:,.0f} {self.salary_period}"
        return "Salary not specified"
    
    @property
    def offers_visa_sponsorship(self):
        """Check if this job offers visa sponsorship"""
        return self.visa_sponsorship in ['available', 'considered']
    
    @property
    def days_since_posted(self):
        """Calculate days since job was posted"""
        from django.utils import timezone
        return (timezone.now() - self.created_at).days
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            import uuid
            base_slug = slugify(f"{self.title} {self.company.name}")
            self.slug = f"{base_slug}-{str(uuid.uuid4())[:8]}"
        super().save(*args, **kwargs)
    
    def increment_view_count(self):
        """Increment the view count for this job"""
        self.view_count = models.F('view_count') + 1
        self.save(update_fields=['view_count'])


class JobSavedByUser(models.Model):
    """
    Track jobs saved/bookmarked by users
    """
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='saved_jobs'
    )
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name='saved_by_users'
    )
    saved_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(
        blank=True,
        max_length=500,
        help_text="Personal notes about this job"
    )
    
    class Meta:
        verbose_name = _('Saved Job')
        verbose_name_plural = _('Saved Jobs')
        unique_together = ['user', 'job']
        ordering = ['-saved_at']
    
    def __str__(self):
        return f"{self.user.full_name} saved {self.job.title}"


class JobAlert(models.Model):
    """
    Job alert subscriptions for users
    """
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='job_alerts'
    )
    
    # Alert Criteria
    title = models.CharField(
        max_length=200,
        help_text="Alert name/description"
    )
    keywords = models.CharField(
        max_length=500,
        blank=True,
        help_text="Keywords to search for"
    )
    location_city = models.CharField(max_length=100, blank=True)
    location_region = models.CharField(max_length=100, blank=True)
    job_types = models.JSONField(
        default=list,
        help_text="Job types to include in alert"
    )
    experience_levels = models.JSONField(
        default=list,
        help_text="Experience levels to include"
    )
    industries = models.JSONField(
        default=list,
        help_text="Industries to include"
    )
    salary_min = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Minimum salary threshold"
    )
    visa_sponsorship_required = models.BooleanField(
        default=True,
        help_text="Only include jobs with visa sponsorship"
    )
    
    # Alert Settings
    is_active = models.BooleanField(default=True)
    frequency = models.CharField(
        max_length=20,
        choices=(
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('immediate', 'Immediate'),
        ),
        default='daily'
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_sent = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = _('Job Alert')
        verbose_name_plural = _('Job Alerts')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.full_name} - {self.title}"