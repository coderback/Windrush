from rest_framework import generics, status, filters
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Count, F, Case, When, IntegerField
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta, datetime

from .models import Application, ApplicationStatusHistory, ApplicationMessage
from .serializers import (
    ApplicationListSerializer, ApplicationDetailSerializer, ApplicationCreateSerializer,
    SpeculativeApplicationCreateSerializer, ApplicationStatusUpdateSerializer,
    ApplicationStatusHistorySerializer, ApplicationMessageSerializer,
    ApplicationMessageCreateSerializer, ApplicationSearchSerializer, ApplicationStatsSerializer
)
from jobs.models import Job
from companies.models import Company


class ApplicationListCreateView(generics.ListCreateAPIView):
    """
    List user's applications or create a new application.
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['job__title', 'company__name']
    filterset_fields = ['status', 'application_type', 'requires_sponsorship']
    ordering_fields = ['applied_at', 'updated_at', 'status']
    ordering = ['-applied_at']
    
    def get_queryset(self):
        """Get applications for current user with optimized queries"""
        return Application.objects.filter(
            applicant=self.request.user
        ).select_related('job', 'company').annotate(
            days_since_applied=(timezone.now().date() - F('applied_at__date')),
            is_active=Case(
                When(status__in=['applied', 'under_review', 'interviewing', 'offered'], then=1),
                default=0,
                output_field=IntegerField()
            ),
            is_successful=Case(
                When(status='hired', then=1),
                default=0,
                output_field=IntegerField()
            ),
            is_rejected=Case(
                When(status='rejected', then=1),
                default=0,
                output_field=IntegerField()
            )
        )
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.request.method == 'POST':
            return ApplicationCreateSerializer
        return ApplicationListSerializer


class ApplicationDetailView(generics.RetrieveAPIView):
    """
    Retrieve detailed information about an application.
    """
    serializer_class = ApplicationDetailSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get applications accessible to current user"""
        user = self.request.user
        
        # Job seekers can only see their own applications
        if user.user_type == 'job_seeker':
            return Application.objects.filter(applicant=user)
        
        # Employers can see applications to their companies' jobs
        elif user.user_type == 'employer':
            return Application.objects.filter(
                Q(applicant=user) |  # Their own applications if they applied somewhere
                Q(company__created_by=user)  # Applications to their companies
            )
        
        # Admins can see all applications
        else:
            return Application.objects.all()
    
    def get_object(self):
        """Get application and mark as viewed by employer"""
        obj = super().get_object()
        
        # Mark as viewed by employer if accessed by employer
        if (self.request.user.user_type == 'employer' and 
            obj.company.created_by == self.request.user and 
            not obj.viewed_by_employer):
            
            Application.objects.filter(id=obj.id).update(
                viewed_by_employer=True,
                viewed_at=timezone.now()
            )
            obj.refresh_from_db()
        
        return obj


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def apply_to_job(request, job_id):
    """Apply to a specific job"""
    job = get_object_or_404(Job, id=job_id, is_active=True, status='active')
    
    # Check if user has already applied
    if Application.objects.filter(applicant=request.user, job=job).exists():
        return Response(
            {'error': 'You have already applied to this job'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Create application data
    data = request.data.copy()
    data['job'] = job.id
    data['company'] = job.company.id
    
    serializer = ApplicationCreateSerializer(data=data, context={'request': request})
    if serializer.is_valid():
        application = serializer.save()
        
        # Increment job application count
        Job.objects.filter(id=job.id).update(application_count=F('application_count') + 1)
        
        return Response({
            'message': 'Application submitted successfully',
            'application_id': application.id
        }, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_speculative_application(request, company_id):
    """Submit a speculative application to a company"""
    company = get_object_or_404(Company, id=company_id)
    
    # Check if user has already sent speculative application
    if Application.objects.filter(
        applicant=request.user, 
        company=company, 
        application_type='speculative'
    ).exists():
        return Response(
            {'error': 'You have already sent a speculative application to this company'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Create application data
    data = request.data.copy()
    data['company'] = company.id
    
    serializer = SpeculativeApplicationCreateSerializer(data=data, context={'request': request})
    if serializer.is_valid():
        application = serializer.save()
        
        return Response({
            'message': 'Speculative application submitted successfully',
            'application_id': application.id
        }, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_application_status(request, application_id):
    """Update application status (employer only)"""
    application = get_object_or_404(Application, id=application_id)
    
    # Check permissions - only company owner can update status
    if request.user != application.company.created_by:
        return Response(
            {'error': 'You do not have permission to update this application'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    serializer = ApplicationStatusUpdateSerializer(
        application, 
        data=request.data, 
        partial=True,
        context={'request': request}
    )
    
    if serializer.is_valid():
        serializer.save()
        return Response({
            'message': 'Application status updated successfully',
            'application': ApplicationDetailSerializer(application).data
        })
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ApplicationStatusHistoryView(generics.ListAPIView):
    """Get status history for an application"""
    serializer_class = ApplicationStatusHistorySerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        application_id = self.kwargs.get('application_id')
        application = get_object_or_404(Application, id=application_id)
        
        # Check permissions
        user = self.request.user
        if not (application.applicant == user or 
                application.company.created_by == user or 
                user.is_staff):
            return ApplicationStatusHistory.objects.none()
        
        return ApplicationStatusHistory.objects.filter(
            application=application
        ).select_related('changed_by').order_by('-changed_at')


class ApplicationMessageListCreateView(generics.ListCreateAPIView):
    """List messages for an application or create a new message"""
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ApplicationMessageCreateSerializer
        return ApplicationMessageSerializer
    
    def get_queryset(self):
        application_id = self.kwargs.get('application_id')
        application = get_object_or_404(Application, id=application_id)
        
        # Check permissions
        user = self.request.user
        if not (application.applicant == user or 
                application.company.created_by == user):
            return ApplicationMessage.objects.none()
        
        # Mark messages as read when viewed
        ApplicationMessage.objects.filter(
            application=application,
            recipient=user,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())
        
        return ApplicationMessage.objects.filter(
            application=application
        ).select_related('sender', 'recipient').order_by('-created_at')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def application_search(request):
    """Advanced application search for the current user"""
    serializer = ApplicationSearchSerializer(data=request.query_params)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    
    # Start with user's applications
    queryset = Application.objects.filter(
        applicant=request.user
    ).select_related('job', 'company')
    
    # Apply filters
    statuses = data.get('status')
    if statuses:
        queryset = queryset.filter(status__in=statuses)
    
    application_type = data.get('application_type')
    if application_type:
        queryset = queryset.filter(application_type=application_type)
    
    company = data.get('company')
    if company:
        queryset = queryset.filter(company__name__icontains=company)
    
    job_title = data.get('job_title')
    if job_title:
        queryset = queryset.filter(job__title__icontains=job_title)
    
    applied_since = data.get('applied_since')
    if applied_since:
        queryset = queryset.filter(applied_at__date__gte=applied_since)
    
    applied_until = data.get('applied_until')
    if applied_until:
        queryset = queryset.filter(applied_at__date__lte=applied_until)
    
    requires_sponsorship = data.get('requires_sponsorship')
    if requires_sponsorship is not None:
        queryset = queryset.filter(requires_sponsorship=requires_sponsorship)
    
    # Apply ordering
    ordering = data.get('ordering', '-applied_at')
    queryset = queryset.order_by(ordering)
    
    # Paginate results
    from rest_framework.pagination import PageNumberPagination
    
    paginator = PageNumberPagination()
    paginator.page_size = 20
    page = paginator.paginate_queryset(queryset, request)
    
    if page is not None:
        serializer = ApplicationListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
    
    serializer = ApplicationListSerializer(queryset, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def application_stats(request):
    """Get application statistics for current user"""
    user = request.user
    
    # Base queryset for user's applications
    applications = Application.objects.filter(applicant=user)
    
    # Calculate statistics
    stats = {
        'total_applications': applications.count(),
        'job_applications': applications.filter(application_type='job_application').count(),
        'speculative_applications': applications.filter(application_type='speculative').count(),
        'active_applications': applications.filter(
            status__in=['applied', 'under_review', 'interviewing', 'offered']
        ).count(),
        'successful_applications': applications.filter(status='hired').count(),
        'rejected_applications': applications.filter(status='rejected').count(),
        'by_status': dict(
            applications.values('status')
            .annotate(count=Count('id'))
            .values_list('status', 'count')
        ),
        'by_month': {}
    }
    
    # Calculate applications by month for the last 12 months
    twelve_months_ago = timezone.now() - timedelta(days=365)
    monthly_applications = applications.filter(
        applied_at__gte=twelve_months_ago
    ).extra(
        select={'month': "strftime('%%Y-%%m', applied_at)"}
    ).values('month').annotate(count=Count('id')).order_by('month')
    
    stats['by_month'] = {item['month']: item['count'] for item in monthly_applications}
    
    return Response(stats)


# Employer-specific views
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employer_applications(request):
    """Get applications for employer's companies"""
    if request.user.user_type != 'employer':
        return Response(
            {'error': 'Only employers can access this endpoint'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Get applications to employer's companies
    applications = Application.objects.filter(
        company__created_by=request.user
    ).select_related('job', 'company', 'applicant').annotate(
        days_since_applied=(timezone.now().date() - F('applied_at__date'))
    ).order_by('-applied_at')
    
    # Apply filters
    status_filter = request.query_params.get('status')
    if status_filter:
        applications = applications.filter(status=status_filter)
    
    job_id = request.query_params.get('job_id')
    if job_id:
        applications = applications.filter(job_id=job_id)
    
    # Paginate results
    from rest_framework.pagination import PageNumberPagination
    
    paginator = PageNumberPagination()
    paginator.page_size = 20
    page = paginator.paginate_queryset(applications, request)
    
    if page is not None:
        serializer = ApplicationDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
    
    serializer = ApplicationDetailSerializer(applications, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employer_application_stats(request):
    """Get application statistics for employer"""
    if request.user.user_type != 'employer':
        return Response(
            {'error': 'Only employers can access this endpoint'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Get applications to employer's companies
    applications = Application.objects.filter(company__created_by=request.user)
    
    stats = {
        'total_applications': applications.count(),
        'new_applications': applications.filter(status='applied').count(),
        'under_review': applications.filter(status='under_review').count(),
        'interviewing': applications.filter(status='interviewing').count(),
        'hired': applications.filter(status='hired').count(),
        'rejected': applications.filter(status='rejected').count(),
        'unviewed_applications': applications.filter(viewed_by_employer=False).count(),
        'recent_applications': applications.filter(
            applied_at__gte=timezone.now() - timedelta(days=7)
        ).count(),
        'by_job': list(
            applications.values('job__title', 'job_id')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
    }
    
    return Response(stats)
