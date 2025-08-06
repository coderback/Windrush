from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from django.urls import reverse


class Company(models.Model):
    """
    Company model representing UK visa sponsor companies
    Based on the official UK sponsor license database
    """
    COMPANY_SIZE_CHOICES = (
        ('startup', '1-10 employees'),
        ('small', '11-50 employees'),
        ('medium', '51-200 employees'),
        ('large', '201-1000 employees'),
        ('enterprise', '1000+ employees'),
    )
    
    SPONSOR_STATUS_CHOICES = (
        ('active', 'Active Sponsor'),
        ('suspended', 'Suspended'),
        ('revoked', 'Revoked'),
        ('pending', 'Pending Verification'),
    )
    
    VISA_TYPES_CHOICES = (
        ('skilled_worker', 'Skilled Worker'),
        ('global_talent', 'Global Talent'),
        ('graduate', 'Graduate Route'),
        ('student', 'Student'),
        ('temporary_worker', 'Temporary Worker'),
    )
    
    # Basic Company Information
    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Official company name"
    )
    slug = models.SlugField(
        max_length=255,
        unique=True,
        help_text="URL-friendly company identifier"
    )
    
    # Contact Information
    website = models.URLField(blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[RegexValidator(
            regex=r'^\+?1?\d{9,15}$',
            message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed."
        )]
    )
    
    # Company Details
    description = models.TextField(
        blank=True,
        max_length=2000,
        help_text="Company description and overview"
    )
    industry = models.CharField(
        max_length=100,
        blank=True,
        help_text="Primary industry sector"
    )
    company_size = models.CharField(
        max_length=20,
        choices=COMPANY_SIZE_CHOICES,
        blank=True,
        help_text="Company size range"
    )
    founded_year = models.IntegerField(
        null=True,
        blank=True,
        help_text="Year company was founded"
    )
    
    # Location Information
    headquarters_address = models.TextField(
        blank=True,
        help_text="Main office address"
    )
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='United Kingdom')
    postcode = models.CharField(
        max_length=10,
        blank=True,
        validators=[RegexValidator(
            regex=r'^[A-Z]{1,2}[0-9]{1,2}[A-Z]?\s?[0-9][A-Z]{2}$',
            message="Enter a valid UK postcode"
        )]
    )
    
    # Visa Sponsorship Information
    is_sponsor = models.BooleanField(
        default=True,
        help_text="Whether company is a licensed visa sponsor"
    )
    sponsor_license_number = models.CharField(
        max_length=50,
        blank=True,
        unique=True,
        null=True,
        help_text="Official sponsor license number from UK government"
    )
    sponsor_status = models.CharField(
        max_length=20,
        choices=SPONSOR_STATUS_CHOICES,
        default='active',
        help_text="Current sponsor license status"
    )
    sponsor_types = models.JSONField(
        default=list,
        help_text="Types of visas this company can sponsor"
    )
    sponsor_verified_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when sponsor status was last verified"
    )
    
    # Company Profile & Branding
    logo = models.ImageField(
        upload_to='company_logos/',
        null=True,
        blank=True,
        help_text="Company logo image"
    )
    banner_image = models.ImageField(
        upload_to='company_banners/',
        null=True,
        blank=True,
        help_text="Company banner/cover image"
    )
    
    # Company Culture & Benefits
    benefits = models.JSONField(
        default=list,
        help_text="List of company benefits and perks"
    )
    company_values = models.TextField(
        blank=True,
        max_length=1000,
        help_text="Company values and culture"
    )
    
    # Social Media & Links
    linkedin_url = models.URLField(blank=True, null=True)
    twitter_url = models.URLField(blank=True, null=True)
    glassdoor_url = models.URLField(blank=True, null=True)
    
    # Platform Specific
    is_featured = models.BooleanField(
        default=False,
        help_text="Whether to feature this company prominently"
    )
    is_premium_partner = models.BooleanField(
        default=False,
        help_text="Premium partnership status"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether company profile is active"
    )
    
    # Statistics (can be calculated fields)
    total_jobs_posted = models.IntegerField(default=0)
    total_hires_made = models.IntegerField(default=0)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='companies_created'
    )
    
    class Meta:
        verbose_name = _('Company')
        verbose_name_plural = _('Companies')
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['city']),
            models.Index(fields=['industry']),
            models.Index(fields=['is_sponsor']),
            models.Index(fields=['sponsor_status']),
        ]
    
    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse('company_detail', kwargs={'slug': self.slug})
    
    @property
    def active_jobs_count(self):
        """Return count of active job postings"""
        return self.jobs.filter(status='active').count()
    
    @property
    def can_sponsor_skilled_worker(self):
        """Check if company can sponsor Skilled Worker visa"""
        return 'skilled_worker' in self.sponsor_types
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class CompanyReview(models.Model):
    """
    Company reviews from job seekers who have worked there
    """
    RATING_CHOICES = (
        (1, '1 - Poor'),
        (2, '2 - Fair'),
        (3, '3 - Good'),
        (4, '4 - Very Good'),
        (5, '5 - Excellent'),
    )
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    reviewer = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='company_reviews'
    )
    
    # Review Content
    title = models.CharField(max_length=200)
    review_text = models.TextField(max_length=2000)
    
    # Ratings
    overall_rating = models.IntegerField(choices=RATING_CHOICES)
    work_life_balance = models.IntegerField(choices=RATING_CHOICES, null=True, blank=True)
    compensation = models.IntegerField(choices=RATING_CHOICES, null=True, blank=True)
    career_opportunities = models.IntegerField(choices=RATING_CHOICES, null=True, blank=True)
    management = models.IntegerField(choices=RATING_CHOICES, null=True, blank=True)
    culture = models.IntegerField(choices=RATING_CHOICES, null=True, blank=True)
    
    # Employment Details
    job_title = models.CharField(max_length=200, blank=True)
    employment_status = models.CharField(
        max_length=50,
        choices=(
            ('current', 'Current Employee'),
            ('former', 'Former Employee'),
            ('intern', 'Former Intern'),
        ),
        default='former'
    )
    employment_length = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g., '2 years', '6 months'"
    )
    
    # Visa Sponsorship Experience
    received_sponsorship = models.BooleanField(
        null=True,
        blank=True,
        help_text="Did this company provide visa sponsorship?"
    )
    sponsorship_experience = models.TextField(
        blank=True,
        max_length=1000,
        help_text="Details about the visa sponsorship process"
    )
    
    # Review Metadata
    is_anonymous = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    helpful_count = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Company Review')
        verbose_name_plural = _('Company Reviews')
        ordering = ['-created_at']
        unique_together = ['company', 'reviewer']  # One review per user per company
        indexes = [
            models.Index(fields=['company', 'is_approved']),
            models.Index(fields=['overall_rating']),
        ]
    
    def __str__(self):
        return f"{self.company.name} - {self.overall_rating}★ by {self.reviewer.full_name}"