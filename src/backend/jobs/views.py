from rest_framework import generics, status, filters
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Count, F, Case, When, IntegerField
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta

from .models import Job, JobSavedByUser, JobAlert
from .serializers import (
    JobListSerializer, JobDetailSerializer, JobCreateUpdateSerializer,
    JobSearchSerializer, JobSavedByUserSerializer, JobSaveSerializer,
    JobAlertSerializer, JobAlertCreateUpdateSerializer
)


class JobListCreateView(generics.ListCreateAPIView):
    """
    List all jobs or create a new job.
    Supports comprehensive search, filtering, and ordering.
    """
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description', 'required_skills', 'company__name']
    filterset_fields = [
        'job_type', 'experience_level', 'industry', 'remote_policy',
        'visa_sponsorship', 'is_featured', 'is_urgent', 'company'
    ]
    ordering_fields = [
        'created_at', 'title', 'salary_min', 'salary_max', 
        'application_deadline', 'view_count', 'application_count'
    ]
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get jobs with optimized queries and custom filtering"""
        queryset = Job.objects.filter(
            is_active=True,
            status='active'
        ).select_related('company').annotate(
            offers_visa_sponsorship=Case(
                When(visa_sponsorship__in=['available', 'considered'], then=1),
                default=0,
                output_field=IntegerField()
            ),
            days_since_posted=Case(
                When(
                    created_at__gte=timezone.now() - timedelta(days=1),
                    then=0
                ),
                When(
                    created_at__gte=timezone.now() - timedelta(days=7),
                    then=F('created_at__date') - timezone.now().date()
                ),
                default=(F('created_at__date') - timezone.now().date()).days,
                output_field=IntegerField()
            )
        )
        
        # Custom filtering based on query parameters
        location = self.request.query_params.get('location')
        if location:
            queryset = queryset.filter(
                Q(location_city__icontains=location) | 
                Q(location_region__icontains=location)
            )
        
        job_types = self.request.query_params.getlist('job_type')
        if job_types:
            queryset = queryset.filter(job_type__in=job_types)
        
        experience_levels = self.request.query_params.getlist('experience_level')
        if experience_levels:
            queryset = queryset.filter(experience_level__in=experience_levels)
        
        remote_policies = self.request.query_params.getlist('remote_policy')
        if remote_policies:
            queryset = queryset.filter(remote_policy__in=remote_policies)
        
        salary_min = self.request.query_params.get('salary_min')
        if salary_min:
            try:
                queryset = queryset.filter(salary_min__gte=float(salary_min))
            except ValueError:
                pass
        
        salary_max = self.request.query_params.get('salary_max')
        if salary_max:
            try:
                queryset = queryset.filter(salary_max__lte=float(salary_max))
            except ValueError:
                pass
        
        visa_sponsorship_options = self.request.query_params.getlist('visa_sponsorship')
        if visa_sponsorship_options:
            queryset = queryset.filter(visa_sponsorship__in=visa_sponsorship_options)
        
        required_skills = self.request.query_params.getlist('required_skills')
        if required_skills:
            for skill in required_skills:
                queryset = queryset.filter(required_skills__icontains=skill)
        
        company_name = self.request.query_params.get('company')
        if company_name:
            queryset = queryset.filter(company__name__icontains=company_name)
        
        posted_since = self.request.query_params.get('posted_since')
        if posted_since:
            try:
                days_ago = int(posted_since)
                since_date = timezone.now() - timedelta(days=days_ago)
                queryset = queryset.filter(created_at__gte=since_date)
            except ValueError:
                pass
        
        is_featured = self.request.query_params.get('is_featured')
        if is_featured == 'true':
            queryset = queryset.filter(is_featured=True)
        
        is_urgent = self.request.query_params.get('is_urgent')
        if is_urgent == 'true':
            queryset = queryset.filter(is_urgent=True)
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.request.method == 'POST':
            return JobCreateUpdateSerializer
        return JobListSerializer
    
    def perform_create(self, serializer):
        """Set posted_by when creating job"""
        serializer.save(posted_by=self.request.user)


class JobDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update or delete a job.
    Only job creators or admins can update/delete.
    """
    queryset = Job.objects.select_related('company')
    lookup_field = 'slug'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.request.method in ['PUT', 'PATCH']:
            return JobCreateUpdateSerializer
        return JobDetailSerializer
    
    def get_permissions(self):
        """Only allow read for unauthenticated, write for job owners/admins"""
        if self.request.method == 'GET':
            permission_classes = [IsAuthenticatedOrReadOnly]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]
    
    def get_object(self):
        """Get job and check permissions"""
        obj = get_object_or_404(Job, slug=self.kwargs['slug'])
        
        # Increment view count for GET requests
        if self.request.method == 'GET':
            Job.objects.filter(id=obj.id).update(view_count=F('view_count') + 1)
            obj.refresh_from_db()
        
        # Check permissions for update/delete
        if self.request.method in ['PUT', 'PATCH', 'DELETE']:
            if not (obj.posted_by == self.request.user or self.request.user.is_staff):
                self.permission_denied(
                    self.request,
                    message="You don't have permission to modify this job."
                )
        
        return obj


@api_view(['GET'])
def job_search(request):
    """
    Advanced job search endpoint with comprehensive filtering.
    """
    # Validate search parameters
    serializer = JobSearchSerializer(data=request.query_params)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    
    # Start with base queryset
    queryset = Job.objects.filter(
        is_active=True,
        status='active'
    ).select_related('company').annotate(
        offers_visa_sponsorship=Case(
            When(visa_sponsorship__in=['available', 'considered'], then=1),
            default=0,
            output_field=IntegerField()
        )
    )
    
    # Apply search term
    search = data.get('search')
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search) |
            Q(description__icontains=search) |
            Q(required_skills__icontains=search) |
            Q(company__name__icontains=search)
        )
    
    # Apply filters
    location = data.get('location')
    if location:
        queryset = queryset.filter(
            Q(location_city__icontains=location) | 
            Q(location_region__icontains=location)
        )
    
    job_types = data.get('job_type')
    if job_types:
        queryset = queryset.filter(job_type__in=job_types)
    
    experience_levels = data.get('experience_level')
    if experience_levels:
        queryset = queryset.filter(experience_level__in=experience_levels)
    
    industry = data.get('industry')
    if industry:
        queryset = queryset.filter(industry__icontains=industry)
    
    remote_policies = data.get('remote_policy')
    if remote_policies:
        queryset = queryset.filter(remote_policy__in=remote_policies)
    
    salary_min = data.get('salary_min')
    if salary_min:
        queryset = queryset.filter(salary_min__gte=salary_min)
    
    salary_max = data.get('salary_max')
    if salary_max:
        queryset = queryset.filter(salary_max__lte=salary_max)
    
    visa_sponsorship = data.get('visa_sponsorship')
    if visa_sponsorship:
        queryset = queryset.filter(visa_sponsorship__in=visa_sponsorship)
    
    required_skills = data.get('required_skills')
    if required_skills:
        for skill in required_skills:
            queryset = queryset.filter(required_skills__icontains=skill)
    
    company = data.get('company')
    if company:
        queryset = queryset.filter(company__name__icontains=company)
    
    posted_since = data.get('posted_since')
    if posted_since:
        since_date = timezone.now() - timedelta(days=posted_since)
        queryset = queryset.filter(created_at__gte=since_date)
    
    is_featured = data.get('is_featured')
    if is_featured is not None:
        queryset = queryset.filter(is_featured=is_featured)
    
    is_urgent = data.get('is_urgent')
    if is_urgent is not None:
        queryset = queryset.filter(is_urgent=is_urgent)
    
    # Apply ordering
    ordering = data.get('ordering', '-created_at')
    queryset = queryset.order_by(ordering)
    
    # Paginate results
    from rest_framework.pagination import PageNumberPagination
    
    paginator = PageNumberPagination()
    paginator.page_size = 20
    page = paginator.paginate_queryset(queryset, request)
    
    if page is not None:
        serializer = JobListSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)
    
    serializer = JobListSerializer(queryset, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
def job_stats(request):
    """Get overall job statistics"""
    stats = {
        'total_jobs': Job.objects.filter(is_active=True).count(),
        'active_jobs': Job.objects.filter(status='active', is_active=True).count(),
        'jobs_with_sponsorship': Job.objects.filter(
            visa_sponsorship__in=['available', 'considered'],
            is_active=True
        ).count(),
        'featured_jobs': Job.objects.filter(is_featured=True, is_active=True).count(),
        'remote_jobs': Job.objects.filter(
            remote_policy__in=['remote_only', 'hybrid'],
            is_active=True
        ).count(),
        'top_job_types': list(
            Job.objects.filter(is_active=True)
            .values('job_type')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        ),
        'top_industries': list(
            Job.objects.filter(is_active=True)
            .values('industry')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        ),
        'top_locations': list(
            Job.objects.filter(is_active=True)
            .values('location_city', 'location_region')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        ),
        'salary_ranges': {
            'under_30k': Job.objects.filter(
                salary_max__lt=30000, is_active=True
            ).count(),
            '30k_50k': Job.objects.filter(
                salary_min__gte=30000, salary_max__lte=50000, is_active=True
            ).count(),
            '50k_70k': Job.objects.filter(
                salary_min__gte=50000, salary_max__lte=70000, is_active=True
            ).count(),
            'over_70k': Job.objects.filter(
                salary_min__gt=70000, is_active=True
            ).count(),
        }
    }
    
    return Response(stats)


@api_view(['GET'])
def featured_jobs(request):
    """Get featured jobs for homepage"""
    jobs = Job.objects.filter(
        is_featured=True,
        is_active=True,
        status='active'
    ).select_related('company').annotate(
        offers_visa_sponsorship=Case(
            When(visa_sponsorship__in=['available', 'considered'], then=1),
            default=0,
            output_field=IntegerField()
        )
    ).order_by('-is_urgent', '-created_at')[:6]
    
    serializer = JobListSerializer(jobs, many=True, context={'request': request})
    return Response(serializer.data)


# Saved Jobs Views
class SavedJobsListView(generics.ListAPIView):
    """List user's saved jobs"""
    serializer_class = JobSavedByUserSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return JobSavedByUser.objects.filter(
            user=self.request.user
        ).select_related('job__company').order_by('-saved_at')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_job(request, job_id):
    """Save a job for later viewing"""
    job = get_object_or_404(Job, id=job_id, is_active=True)
    
    # Check if already saved
    saved_job, created = JobSavedByUser.objects.get_or_create(
        user=request.user,
        job=job,
        defaults={'notes': request.data.get('notes', '')}
    )
    
    if created:
        return Response({
            'message': 'Job saved successfully',
            'saved_job_id': saved_job.id
        }, status=status.HTTP_201_CREATED)
    else:
        return Response({
            'message': 'Job already saved',
            'saved_job_id': saved_job.id
        }, status=status.HTTP_200_OK)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def unsave_job(request, job_id):
    """Remove a job from saved jobs"""
    job = get_object_or_404(Job, id=job_id)
    
    try:
        saved_job = JobSavedByUser.objects.get(user=request.user, job=job)
        saved_job.delete()
        return Response({'message': 'Job removed from saved jobs'})
    except JobSavedByUser.DoesNotExist:
        return Response(
            {'error': 'Job is not in your saved jobs'},
            status=status.HTTP_404_NOT_FOUND
        )


# Job Alerts Views
class JobAlertListCreateView(generics.ListCreateAPIView):
    """List user's job alerts or create a new alert"""
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return JobAlertCreateUpdateSerializer
        return JobAlertSerializer
    
    def get_queryset(self):
        return JobAlert.objects.filter(user=self.request.user).order_by('-created_at')


class JobAlertDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a job alert"""
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return JobAlertCreateUpdateSerializer
        return JobAlertSerializer
    
    def get_queryset(self):
        return JobAlert.objects.filter(user=self.request.user)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_job_alert(request, alert_id):
    """Toggle job alert active status"""
    alert = get_object_or_404(JobAlert, id=alert_id, user=request.user)
    
    alert.is_active = not alert.is_active
    alert.save()
    
    return Response({
        'message': f'Job alert {"activated" if alert.is_active else "deactivated"}',
        'is_active': alert.is_active
    })
