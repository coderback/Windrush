from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Auth root endpoint
    path('', views.auth_root, name='auth_root'),
    
    # Authentication
    path('register/', views.UserRegistrationView.as_view(), name='register'),
    path('login/', views.UserLoginView.as_view(), name='login'),
    path('logout/', views.UserLogoutView.as_view(), name='logout'),
    
    # Profile management
    path('profile/', views.UserProfileView.as_view(), name='profile'),
    path('job-seeker-profile/', views.JobSeekerProfileView.as_view(), name='job_seeker_profile'),
    
    # Password management
    path('change-password/', views.ChangePasswordView.as_view(), name='change_password'),
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='password_reset'),
    path('password-reset-confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    
    # Account management
    path('stats/', views.user_stats_view, name='user_stats'),
    path('delete-account/', views.delete_account_view, name='delete_account'),
    path('verify-email/', views.verify_email_view, name='verify_email'),
    path('resend-verification/', views.resend_verification_email_view, name='resend_verification'),
]