from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.contrib.auth import login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from django.http import JsonResponse

from .models import User, JobSeekerProfile, EmailVerificationToken, PasswordResetToken
from .serializers import (
    UserRegistrationSerializer, UserLoginSerializer, UserProfileSerializer,
    JobSeekerProfileSerializer, JobSeekerProfileCreateUpdateSerializer,
    ChangePasswordSerializer, PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer, EmailVerificationSerializer
)
from .email_service import EmailService


def auth_root(request):
    """Auth API root endpoint"""
    return JsonResponse({
        'message': 'Windrush Authentication API',
        'endpoints': {
            'register': '/api/auth/register/',
            'login': '/api/auth/login/',
            'logout': '/api/auth/logout/',
            'profile': '/api/auth/profile/',
            'job_seeker_profile': '/api/auth/job-seeker-profile/',
            'change_password': '/api/auth/change-password/',
            'password_reset': '/api/auth/password-reset/',
            'stats': '/api/auth/stats/',
            'verify_email': '/api/auth/verify-email/',
            'delete_account': '/api/auth/delete-account/',
        }
    })


class UserRegistrationView(generics.CreateAPIView):
    """User registration endpoint"""
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # User starts unverified
        user.is_verified = False
        user.save()
        
        # Create verification token
        verification_token = EmailVerificationToken.objects.create(user=user)
        
        # Send verification email
        EmailService.send_verification_email(user, verification_token)
        
        # Create job seeker profile if user type is job_seeker
        if user.user_type == 'job_seeker':
            JobSeekerProfile.objects.create(user=user)
        
        return Response({
            'message': 'Registration successful. Please check your email to verify your account.',
            'user': UserProfileSerializer(user).data,
            'verification_required': True
        }, status=status.HTTP_201_CREATED)


class UserLoginView(generics.GenericAPIView):
    """User login endpoint"""
    serializer_class = UserLoginSerializer
    permission_classes = [permissions.AllowAny]
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        
        # Check if email is verified
        if not user.is_verified:
            return Response({
                'message': 'Please verify your email address before logging in.',
                'email_verification_required': True,
                'email': user.email
            }, status=status.HTTP_403_FORBIDDEN)
        
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
        user = User.objects.get(email=email)
        
        # Invalidate any existing reset tokens
        PasswordResetToken.objects.filter(user=user, is_used=False).update(is_used=True)
        
        # Create new reset token
        reset_token = PasswordResetToken.objects.create(user=user)
        
        # Send reset email
        EmailService.send_password_reset_email(user, reset_token)
        
        return Response({
            'message': f'Password reset instructions sent to {email}'
        })


class PasswordResetConfirmView(generics.GenericAPIView):
    """Password reset confirmation endpoint"""
    serializer_class = PasswordResetConfirmSerializer
    permission_classes = [permissions.AllowAny]
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        token_value = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']
        
        # Get the token
        reset_token = PasswordResetToken.objects.get(token=token_value, is_used=False)
        user = reset_token.user
        
        # Reset password
        user.set_password(new_password)
        user.save()
        
        # Mark token as used
        reset_token.is_used = True
        reset_token.save()
        
        # Delete all user tokens to force re-login
        Token.objects.filter(user=user).delete()
        
        # Send confirmation email
        EmailService.send_password_reset_confirmation_email(user)
        
        return Response({
            'message': 'Password reset successful. Please login with your new password.'
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
@permission_classes([permissions.AllowAny])
def verify_email_view(request):
    """Verify user email with token"""
    serializer = EmailVerificationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    token_value = serializer.validated_data['token']
    
    # Get the token
    verification_token = EmailVerificationToken.objects.get(token=token_value, is_used=False)
    user = verification_token.user
    
    # Mark email as verified
    user.is_verified = True
    user.save()
    
    # Mark token as used
    verification_token.is_used = True
    verification_token.save()
    
    # Create auth token for immediate login
    auth_token, created = Token.objects.get_or_create(user=user)
    
    # Send welcome email
    EmailService.send_welcome_email(user)
    
    return Response({
        'message': 'Email verified successfully! You are now logged in.',
        'user': UserProfileSerializer(user).data,
        'token': auth_token.key
    })


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def resend_verification_email_view(request):
    """Resend email verification"""
    email = request.data.get('email')
    
    if not email:
        return Response({
            'message': 'Email address is required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({
            'message': 'No user found with this email address'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if user.is_verified:
        return Response({
            'message': 'Email is already verified'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Invalidate existing tokens
    EmailVerificationToken.objects.filter(user=user, is_used=False).update(is_used=True)
    
    # Create new verification token
    verification_token = EmailVerificationToken.objects.create(user=user)
    
    # Send verification email
    EmailService.send_verification_email(user, verification_token)
    
    return Response({
        'message': 'Verification email sent'
    })