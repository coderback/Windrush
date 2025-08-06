from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.contrib.auth import login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404

from .models import User, JobSeekerProfile
from .serializers import (
    UserRegistrationSerializer, UserLoginSerializer, UserProfileSerializer,
    JobSeekerProfileSerializer, JobSeekerProfileCreateUpdateSerializer,
    ChangePasswordSerializer, PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer
)


class UserRegistrationView(generics.CreateAPIView):
    """User registration endpoint"""
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # Create auth token
        token, created = Token.objects.get_or_create(user=user)
        
        # Create job seeker profile if user type is job_seeker
        if user.user_type == 'job_seeker':
            JobSeekerProfile.objects.create(user=user)
        
        return Response({
            'message': 'Registration successful',
            'user': UserProfileSerializer(user).data,
            'token': token.key
        }, status=status.HTTP_201_CREATED)


class UserLoginView(generics.GenericAPIView):
    """User login endpoint"""
    serializer_class = UserLoginSerializer
    permission_classes = [permissions.AllowAny]
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        login(request, user)
        
        # Get or create token
        token, created = Token.objects.get_or_create(user=user)
        
        return Response({
            'message': 'Login successful',
            'user': UserProfileSerializer(user).data,
            'token': token.key
        })


class UserLogoutView(generics.GenericAPIView):
    """User logout endpoint"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, *args, **kwargs):
        try:
            # Delete the token
            request.user.auth_token.delete()
        except:
            pass
        
        logout(request)
        return Response({
            'message': 'Logout successful'
        })


class UserProfileView(generics.RetrieveUpdateAPIView):
    """User profile view and update"""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        return self.request.user


class JobSeekerProfileView(generics.RetrieveUpdateAPIView):
    """Job seeker profile view and update"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return JobSeekerProfileCreateUpdateSerializer
        return JobSeekerProfileSerializer
    
    def get_object(self):
        user = self.request.user
        if user.user_type != 'job_seeker':
            raise permissions.PermissionDenied("Only job seekers can access this endpoint")
        
        profile, created = JobSeekerProfile.objects.get_or_create(user=user)
        return profile


class ChangePasswordView(generics.GenericAPIView):
    """Change password endpoint"""
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        
        # Delete all existing tokens to force re-login
        Token.objects.filter(user=user).delete()
        
        return Response({
            'message': 'Password changed successfully. Please login again.'
        })


class PasswordResetRequestView(generics.GenericAPIView):
    """Password reset request endpoint"""
    serializer_class = PasswordResetRequestSerializer
    permission_classes = [permissions.AllowAny]
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        
        # In a real implementation, you would:
        # 1. Generate a reset token
        # 2. Send email with reset link
        # 3. Store token with expiry
        
        # For now, we'll just return success
        return Response({
            'message': f'Password reset instructions sent to {email}'
        })


class PasswordResetConfirmView(generics.GenericAPIView):
    """Password reset confirmation endpoint"""
    serializer_class = PasswordResetConfirmSerializer
    permission_classes = [permissions.AllowAny]
    
    def post(self, request, *args, **kwargs):
        # In a real implementation, you would:
        # 1. Validate the reset token from URL params
        # 2. Check if token is not expired
        # 3. Reset the password
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # For now, just return success
        return Response({
            'message': 'Password reset successful'
        })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def user_stats_view(request):
    """Get user statistics"""
    user = request.user
    
    if user.user_type == 'job_seeker':
        # Get job seeker stats
        applications = user.applications.all()
        saved_jobs = user.saved_jobs.all()
        
        stats = {
            'total_applications': applications.count(),
            'active_applications': applications.filter(
                status__in=['submitted', 'reviewed', 'shortlisted', 'interviewing']
            ).count(),
            'successful_applications': applications.filter(status='offer_accepted').count(),
            'saved_jobs': saved_jobs.count(),
            'profile_completion': _calculate_profile_completion(user),
        }
    
    elif user.user_type == 'employer':
        # Get employer stats  
        companies = user.companies_created.all()
        jobs = user.jobs_posted.all()
        
        stats = {
            'companies_managed': companies.count(),
            'jobs_posted': jobs.count(),
            'active_jobs': jobs.filter(status='active').count(),
            'total_applications_received': sum(
                job.applications.count() for job in jobs
            ),
        }
    
    else:
        stats = {}
    
    return Response(stats)


def _calculate_profile_completion(user):
    """Calculate profile completion percentage"""
    if user.user_type != 'job_seeker':
        return 0
    
    try:
        profile = user.job_seeker_profile
    except JobSeekerProfile.DoesNotExist:
        return 0
    
    fields_to_check = [
        'phone_number', 'nationality', 'visa_status', 'education_level',
        'field_of_study', 'university', 'skills', 'bio', 'primary_cv'
    ]
    
    completed_fields = 0
    for field in fields_to_check:
        value = getattr(profile, field, None)
        if value:
            if isinstance(value, list) and len(value) > 0:
                completed_fields += 1
            elif isinstance(value, str) and value.strip():
                completed_fields += 1
            elif value is not None:
                completed_fields += 1
    
    return min(100, int((completed_fields / len(fields_to_check)) * 100))


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def delete_account_view(request):
    """Delete user account"""
    user = request.user
    
    # In a real implementation, you might want to:
    # 1. Soft delete instead of hard delete
    # 2. Anonymize data instead of deleting
    # 3. Send confirmation email
    # 4. Add additional confirmation steps
    
    user.delete()
    
    return Response({
        'message': 'Account deleted successfully'
    }, status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def verify_email_view(request):
    """Verify user email"""
    user = request.user
    
    # In a real implementation, you would:
    # 1. Check verification token from request
    # 2. Validate token
    # 3. Mark email as verified
    
    user.is_verified = True
    user.save()
    
    return Response({
        'message': 'Email verified successfully'
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def resend_verification_email_view(request):
    """Resend email verification"""
    user = request.user
    
    if user.is_verified:
        return Response({
            'message': 'Email is already verified'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # In a real implementation, you would:
    # 1. Generate new verification token
    # 2. Send verification email
    
    return Response({
        'message': 'Verification email sent'
    })