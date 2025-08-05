from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, JobSeekerProfile


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom User admin interface"""
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'username')}),
        (_('Windrush specific'), {'fields': ('user_type', 'is_verified', 'is_premium')}),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'first_name', 'last_name', 'password1', 'password2', 'user_type'),
        }),
    )
    
    list_display = ('email', 'full_name', 'user_type', 'is_verified', 'is_premium', 'is_staff', 'created_at')
    list_filter = ('user_type', 'is_verified', 'is_premium', 'is_staff', 'is_superuser', 'is_active')
    search_fields = ('email', 'first_name', 'last_name', 'username')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(JobSeekerProfile)
class JobSeekerProfileAdmin(admin.ModelAdmin):
    """Job Seeker Profile admin interface"""
    
    list_display = (
        'user', 
        'visa_status', 
        'education_level', 
        'years_of_experience', 
        'is_profile_public',
        'is_available_for_work',
        'created_at'
    )
    
    list_filter = (
        'visa_status', 
        'is_profile_public', 
        'is_available_for_work',
        'years_of_experience'
    )
    
    search_fields = (
        'user__email',
        'user__first_name', 
        'user__last_name',
        'university',
        'field_of_study'
    )
    
    fieldsets = (
        (_('User'), {'fields': ('user',)}),
        (_('Personal Information'), {
            'fields': ('phone_number', 'date_of_birth', 'nationality')
        }),
        (_('Visa Information'), {
            'fields': ('visa_status', 'visa_expiry_date')
        }),
        (_('Education & Experience'), {
            'fields': ('education_level', 'field_of_study', 'university', 'graduation_year', 'years_of_experience')
        }),
        (_('Job Preferences'), {
            'fields': ('job_type_preferences', 'preferred_locations', 'preferred_industries', 'expected_salary_min', 'expected_salary_max')
        }),
        (_('Skills & Bio'), {
            'fields': ('skills', 'bio')
        }),
        (_('Profile Settings'), {
            'fields': ('is_profile_public', 'is_available_for_work')
        }),
        (_('Files'), {
            'fields': ('primary_cv',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)