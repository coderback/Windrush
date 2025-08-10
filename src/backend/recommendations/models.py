from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator


class UserJobPreference(models.Model):
    """
    Enhanced user preferences for job recommendations
    """
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='job_preferences'
    )
    
    # Location preferences
    preferred_locations = models.JSONField(
        default=list,
        help_text="List of preferred work locations"
    )
    max_commute_distance = models.IntegerField(
        null=True,
        blank=True,
        help_text="Maximum commute distance in miles"
    )
    open_to_remote = models.BooleanField(default=True)
    open_to_hybrid = models.BooleanField(default=True)
    
    # Job type preferences
    preferred_job_types = models.JSONField(
        default=list,
        help_text="Preferred job types/categories"
    )
    preferred_industries = models.JSONField(
        default=list,
        help_text="Preferred industries"
    )
    experience_level = models.CharField(
        max_length=20,
        choices=[
            ('entry', 'Entry Level'),
            ('mid', 'Mid Level'),
            ('senior', 'Senior Level'),
            ('lead', 'Lead/Principal'),
            ('executive', 'Executive'),
        ],
        default='mid'
    )
    
    # Salary preferences
    min_salary = models.IntegerField(null=True, blank=True)
    max_salary = models.IntegerField(null=True, blank=True)
    salary_currency = models.CharField(max_length=3, default='GBP')
    
    # Skills and keywords
    key_skills = models.JSONField(
        default=list,
        help_text="List of key skills for matching"
    )
    avoid_keywords = models.JSONField(
        default=list,
        help_text="Keywords to avoid in job recommendations"
    )
    
    # Company preferences
    preferred_company_sizes = models.JSONField(
        default=list,
        help_text="Preferred company sizes"
    )
    avoid_companies = models.JSONField(
        default=list,
        help_text="Company IDs to avoid"
    )
    
    # Visa sponsorship
    requires_sponsorship = models.BooleanField(default=True)
    visa_types_needed = models.JSONField(
        default=list,
        help_text="Types of visa sponsorship needed"
    )
    
    # Recommendation settings
    notification_frequency = models.CharField(
        max_length=20,
        choices=[
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
            ('disabled', 'Disabled'),
        ],
        default='weekly'
    )
    max_recommendations = models.IntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(50)]
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('User Job Preference')
        verbose_name_plural = _('User Job Preferences')
    
    def __str__(self):
        return f"Job preferences for {self.user.full_name}"


class JobRecommendation(models.Model):
    """
    Individual job recommendations for users
    """
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='job_recommendations'
    )
    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='recommendations'
    )
    
    # Recommendation scoring
    match_score = models.FloatField(
        help_text="Overall match score (0.0 to 1.0)"
    )
    skill_match_score = models.FloatField(default=0.0)
    location_match_score = models.FloatField(default=0.0)
    salary_match_score = models.FloatField(default=0.0)
    company_match_score = models.FloatField(default=0.0)
    experience_match_score = models.FloatField(default=0.0)
    
    # Recommendation reasons
    match_reasons = models.JSONField(
        default=list,
        help_text="List of reasons why this job was recommended"
    )
    
    # User interaction
    viewed = models.BooleanField(default=False)
    viewed_at = models.DateTimeField(null=True, blank=True)
    clicked = models.BooleanField(default=False)
    clicked_at = models.DateTimeField(null=True, blank=True)
    applied = models.BooleanField(default=False)
    applied_at = models.DateTimeField(null=True, blank=True)
    
    # Feedback
    feedback = models.CharField(
        max_length=20,
        choices=[
            ('helpful', 'Helpful'),
            ('not_helpful', 'Not Helpful'),
            ('not_interested', 'Not Interested'),
            ('already_applied', 'Already Applied'),
        ],
        null=True,
        blank=True
    )
    feedback_at = models.DateTimeField(null=True, blank=True)
    feedback_notes = models.TextField(blank=True, max_length=500)
    
    # Metadata
    recommendation_algorithm = models.CharField(
        max_length=50,
        default='rule_based_v1',
        help_text="Algorithm used to generate this recommendation"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('Job Recommendation')
        verbose_name_plural = _('Job Recommendations')
        unique_together = ['user', 'job']
        ordering = ['-match_score', '-created_at']
        indexes = [
            models.Index(fields=['user', '-match_score']),
            models.Index(fields=['job', '-match_score']),
            models.Index(fields=['user', 'viewed', 'clicked']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.job.title} recommended to {self.user.full_name} ({self.match_score:.2f})"
    
    def mark_viewed(self):
        """Mark recommendation as viewed"""
        if not self.viewed:
            from django.utils import timezone
            self.viewed = True
            self.viewed_at = timezone.now()
            self.save(update_fields=['viewed', 'viewed_at'])
    
    def mark_clicked(self):
        """Mark recommendation as clicked"""
        if not self.clicked:
            from django.utils import timezone
            self.clicked = True
            self.clicked_at = timezone.now()
            self.save(update_fields=['clicked', 'clicked_at'])


class RecommendationBatch(models.Model):
    """
    Batch of recommendations generated for a user
    """
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='recommendation_batches'
    )
    
    # Batch metadata
    algorithm_version = models.CharField(max_length=50, default='rule_based_v1')
    total_recommendations = models.IntegerField()
    average_score = models.FloatField()
    generation_time_ms = models.IntegerField(
        help_text="Time taken to generate recommendations in milliseconds"
    )
    
    # User preferences snapshot (for analysis)
    preferences_snapshot = models.JSONField(
        help_text="Snapshot of user preferences when batch was generated"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('Recommendation Batch')
        verbose_name_plural = _('Recommendation Batches')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Batch for {self.user.full_name} - {self.total_recommendations} recommendations"