from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate
from .models import User, JobSeekerProfile, EmailVerificationToken, PasswordResetToken


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration"""
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        validators=[validate_password]
    )
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = [
            'email', 'username', 'first_name', 'last_name', 
            'user_type', 'password', 'password_confirm'
        ]
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError("Passwords don't match")
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User.objects.create_user(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserLoginSerializer(serializers.Serializer):
    """Serializer for user login"""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')
        
        if email and password:
            user = authenticate(username=email, password=password)
            if not user:
                raise serializers.ValidationError('Invalid credentials')
            if not user.is_active:
                raise serializers.ValidationError('Account is disabled')
            attrs['user'] = user
        else:
            raise serializers.ValidationError('Email and password required')
        return attrs


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for user profile data"""
    full_name = serializers.ReadOnlyField()
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'username', 'first_name', 'last_name',
            'full_name', 'user_type', 'is_verified', 'is_premium',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'email', 'created_at', 'updated_at', 'is_verified']


class JobSeekerProfileSerializer(serializers.ModelSerializer):
    """Serializer for job seeker profile"""
    user = UserProfileSerializer(read_only=True)
    
    class Meta:
        model = JobSeekerProfile
        fields = [
            'user', 'phone_number', 'date_of_birth', 'nationality',
            'visa_status', 'visa_expiry_date', 'education_level',
            'field_of_study', 'university', 'graduation_year',
            'years_of_experience', 'job_type_preferences',
            'preferred_locations', 'preferred_industries',
            'expected_salary_min', 'expected_salary_max',
            'skills', 'bio', 'is_profile_public', 'is_available_for_work',
            'primary_cv', 'created_at', 'updated_at'
        ]
        read_only_fields = ['user', 'created_at', 'updated_at']


class JobSeekerProfileCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating job seeker profile"""
    
    class Meta:
        model = JobSeekerProfile
        fields = [
            'phone_number', 'date_of_birth', 'nationality',
            'visa_status', 'visa_expiry_date', 'education_level',
            'field_of_study', 'university', 'graduation_year',
            'years_of_experience', 'job_type_preferences',
            'preferred_locations', 'preferred_industries',
            'expected_salary_min', 'expected_salary_max',
            'skills', 'bio', 'is_profile_public', 'is_available_for_work',
            'primary_cv'
        ]
    
    def validate_years_of_experience(self, value):
        if value < 0:
            raise serializers.ValidationError("Years of experience cannot be negative")
        if value > 50:
            raise serializers.ValidationError("Years of experience seems too high")
        return value
    
    def validate_expected_salary_min(self, value):
        if value and value < 0:
            raise serializers.ValidationError("Minimum salary cannot be negative")
        return value
    
    def validate_expected_salary_max(self, value):
        if value and value < 0:
            raise serializers.ValidationError("Maximum salary cannot be negative")
        return value
    
    def validate(self, attrs):
        salary_min = attrs.get('expected_salary_min')
        salary_max = attrs.get('expected_salary_max')
        
        if salary_min and salary_max and salary_min > salary_max:
            raise serializers.ValidationError(
                "Minimum salary cannot be greater than maximum salary"
            )
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password"""
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        write_only=True,
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError("New passwords don't match")
        return attrs
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect")
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for password reset request"""
    email = serializers.EmailField()
    
    def validate_email(self, value):
        try:
            User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("No user found with this email address")
        return value


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for password reset confirmation"""
    token = serializers.UUIDField()
    new_password = serializers.CharField(
        write_only=True,
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(write_only=True)
    
    def validate_token(self, value):
        """Validate the reset token"""
        try:
            token = PasswordResetToken.objects.get(token=value, is_used=False)
            if token.is_expired():
                raise serializers.ValidationError("Reset token has expired")
            return value
        except PasswordResetToken.DoesNotExist:
            raise serializers.ValidationError("Invalid or expired reset token")
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError("Passwords don't match")
        return attrs


class EmailVerificationSerializer(serializers.Serializer):
    """Serializer for email verification"""
    token = serializers.UUIDField()
    
    def validate_token(self, value):
        """Validate the verification token"""
        try:
            token = EmailVerificationToken.objects.get(token=value, is_used=False)
            if token.is_expired():
                raise serializers.ValidationError("Verification token has expired")
            return value
        except EmailVerificationToken.DoesNotExist:
            raise serializers.ValidationError("Invalid or expired verification token")