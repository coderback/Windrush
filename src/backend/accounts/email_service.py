from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending various types of emails to users"""
    
    @staticmethod
    def send_verification_email(user, token):
        """Send email verification email"""
        try:
            verification_url = f"{settings.FRONTEND_URL}/auth/verify-email?token={token.token}"
            
            context = {
                'user': user,
                'verification_url': verification_url,
                'site_name': 'Windrush',
                'expiry_hours': 24,
            }
            
            subject = 'Welcome to Windrush - Please verify your email'
            
            # For now, send a simple text email
            # In production, you would use HTML templates
            message = f"""
Hi {user.first_name},

Welcome to Windrush! Please verify your email address by clicking the link below:

{verification_url}

This link will expire in 24 hours.

If you didn't create an account with Windrush, please ignore this email.

Best regards,
The Windrush Team
            """
            
            send_mail(
                subject=subject,
                message=message.strip(),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
            
            logger.info(f"Verification email sent to {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send verification email to {user.email}: {str(e)}")
            return False
    
    @staticmethod
    def send_password_reset_email(user, token):
        """Send password reset email"""
        try:
            reset_url = f"{settings.FRONTEND_URL}/auth/reset-password?token={token.token}"
            
            context = {
                'user': user,
                'reset_url': reset_url,
                'site_name': 'Windrush',
                'expiry_hours': 1,
            }
            
            subject = 'Reset your Windrush password'
            
            message = f"""
Hi {user.first_name},

You requested to reset your password for your Windrush account.

Please click the link below to reset your password:

{reset_url}

This link will expire in 1 hour.

If you didn't request a password reset, please ignore this email.

Best regards,
The Windrush Team
            """
            
            send_mail(
                subject=subject,
                message=message.strip(),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
            
            logger.info(f"Password reset email sent to {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send password reset email to {user.email}: {str(e)}")
            return False
    
    @staticmethod
    def send_password_reset_confirmation_email(user):
        """Send password reset confirmation email"""
        try:
            subject = 'Your Windrush password has been reset'
            
            message = f"""
Hi {user.first_name},

Your password for Windrush has been successfully reset.

If you didn't make this change, please contact our support team immediately.

Best regards,
The Windrush Team
            """
            
            send_mail(
                subject=subject,
                message=message.strip(),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
            
            logger.info(f"Password reset confirmation email sent to {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send password reset confirmation email to {user.email}: {str(e)}")
            return False
    
    @staticmethod
    def send_welcome_email(user):
        """Send welcome email after email verification"""
        try:
            dashboard_url = f"{settings.FRONTEND_URL}/dashboard"
            
            subject = 'Welcome to Windrush - Your account is ready!'
            
            message = f"""
Hi {user.first_name},

Welcome to Windrush! Your email has been verified and your account is now active.

As the UK's premier job board for international talent, we're here to help you find opportunities with visa-sponsoring employers.

Get started by:
1. Completing your profile: {dashboard_url}
2. Browsing jobs from sponsor-licensed companies
3. Setting up job alerts for opportunities that match your skills

We're excited to help you find your next career opportunity in the UK!

Best regards,
The Windrush Team
            """
            
            send_mail(
                subject=subject,
                message=message.strip(),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
            
            logger.info(f"Welcome email sent to {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send welcome email to {user.email}: {str(e)}")
            return False