from rest_framework import generics, status, filters
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Count, Case, When, IntegerField
from django.shortcuts import get_object_or_404

from .models import Company, CompanyReview
from .serializers import (
    CompanyListSerializer, CompanyDetailSerializer, CompanyCreateUpdateSerializer,
    CompanyReviewSerializer, CompanyReviewCreateSerializer, CompanySearchSerializer
)


class CompanyListCreateView(generics.ListCreateAPIView):
    """
    List all companies or create a new company.
    Supports search, filtering, and ordering.
    """
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description', 'industry', 'city']
    filterset_fields = ['industry', 'company_size', 'is_sponsor', 'sponsor_status', 'city', 'region']
    ordering_fields = ['name', 'created_at', 'total_jobs_posted', 'city', 'industry']
    ordering = ['name']
    
    def get_queryset(self):
        """Get companies with optimized queries and custom filtering"""
        queryset = Company.objects.select_related().annotate(
            active_jobs_count=Count(
                'jobs',
                filter=Q(jobs__status='active')
            )
        )
        
        # Custom filtering based on query parameters
        industry = self.request.query_params.get('industry')
        if industry:
            queryset = queryset.filter(industry__icontains=industry)
        
        location = self.request.query_params.get('location')
        if location:
            queryset = queryset.filter(
                Q(city__icontains=location) | Q(region__icontains=location)
            )
        
        company_size = self.request.query_params.get('company_size')
        if company_size:
            queryset = queryset.filter(company_size=company_size)
        
        sponsor_status = self.request.query_params.get('sponsor_status')
        if sponsor_status:
            queryset = queryset.filter(sponsor_status=sponsor_status)
        
        # Note: visa_types filtering temporarily disabled for SQLite compatibility
        # visa_types = self.request.query_params.getlist('visa_types')
        # if visa_types:
        #     for visa_type in visa_types:
        #         queryset = queryset.filter(sponsor_types__contains=[visa_type])
        
        has_active_jobs = self.request.query_params.get('has_active_jobs')
        if has_active_jobs == 'true':
            queryset = queryset.filter(active_jobs_count__gt=0)
        elif has_active_jobs == 'false':
            queryset = queryset.filter(active_jobs_count=0)
        
        is_featured = self.request.query_params.get('is_featured')
        if is_featured == 'true':
            queryset = queryset.filter(is_featured=True)
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.request.method == 'POST':
            return CompanyCreateUpdateSerializer
        return CompanyListSerializer
    
    def perform_create(self, serializer):
        """Set created_by when creating company"""
        serializer.save(created_by=self.request.user)


class CompanyDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update or delete a company.
    Only company creators or admins can update/delete.
    """
    queryset = Company.objects.select_related()
    lookup_field = 'slug'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.request.method in ['PUT', 'PATCH']:
            return CompanyCreateUpdateSerializer
        return CompanyDetailSerializer
    
    def get_permissions(self):
        """Only allow read for unauthenticated, write for company owners/admins"""
        if self.request.method == 'GET':
            permission_classes = [IsAuthenticatedOrReadOnly]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]
    
    def get_object(self):
        """Get company and check permissions"""
        obj = get_object_or_404(Company, slug=self.kwargs['slug'])
        
        # Check permissions for update/delete
        if self.request.method in ['PUT', 'PATCH', 'DELETE']:
            if not (obj.created_by == self.request.user or self.request.user.is_staff):
                self.permission_denied(
                    self.request,
                    message="You don't have permission to modify this company."
                )
        
        return obj


class CompanyReviewListCreateView(generics.ListCreateAPIView):
    """
    List reviews for a company or create a new review.
    """
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        """Get approved reviews for the company"""
        company_slug = self.kwargs.get('company_slug')
        return CompanyReview.objects.filter(
            company__slug=company_slug,
            is_approved=True
        ).select_related('reviewer').order_by('-created_at')
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.request.method == 'POST':
            return CompanyReviewCreateSerializer
        return CompanyReviewSerializer
    
    def perform_create(self, serializer):
        """Set company and reviewer when creating review"""
        company = get_object_or_404(Company, slug=self.kwargs.get('company_slug'))
        serializer.save(company=company, reviewer=self.request.user)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_review_helpful(request, review_id):
    """Mark a review as helpful"""
    review = get_object_or_404(CompanyReview, id=review_id)
    
    # Prevent users from marking their own reviews as helpful
    if review.reviewer == request.user:
        return Response(
            {'error': 'You cannot mark your own review as helpful'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Simple increment - in production, you might want to track which users marked it helpful
    review.helpful_count += 1
    review.save()
    
    return Response({
        'message': 'Review marked as helpful',
        'helpful_count': review.helpful_count
    })


@api_view(['GET'])
def company_search(request):
    """
    Advanced company search endpoint with custom filtering.
    """
    # Validate search parameters
    serializer = CompanySearchSerializer(data=request.query_params)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    
    # Start with base queryset
    queryset = Company.objects.select_related().annotate(
        active_jobs_count=Count(
            'jobs',
            filter=Q(jobs__status='active')
        )
    )
    
    # Apply search term
    search = data.get('search')
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search) |
            Q(industry__icontains=search)
        )
    
    # Apply filters
    industry = data.get('industry')
    if industry:
        queryset = queryset.filter(industry__icontains=industry)
    
    location = data.get('location')
    if location:
        queryset = queryset.filter(
            Q(city__icontains=location) | Q(region__icontains=location)
        )
    
    company_size = data.get('company_size')
    if company_size:
        queryset = queryset.filter(company_size=company_size)
    
    sponsor_status = data.get('sponsor_status')
    if sponsor_status:
        queryset = queryset.filter(sponsor_status=sponsor_status)
    
    # Note: visa_types filtering temporarily disabled for SQLite compatibility  
    # visa_types = data.get('visa_types')
    # if visa_types:
    #     for visa_type in visa_types:
    #         queryset = queryset.filter(sponsor_types__contains=[visa_type])
    
    has_active_jobs = data.get('has_active_jobs')
    if has_active_jobs is not None:
        if has_active_jobs:
            queryset = queryset.filter(active_jobs_count__gt=0)
        else:
            queryset = queryset.filter(active_jobs_count=0)
    
    is_featured = data.get('is_featured')
    if is_featured is not None:
        queryset = queryset.filter(is_featured=is_featured)
    
    # Apply ordering
    ordering = data.get('ordering', 'name')
    queryset = queryset.order_by(ordering)
    
    # Paginate results
    from rest_framework.pagination import PageNumberPagination
    
    paginator = PageNumberPagination()
    paginator.page_size = 20
    page = paginator.paginate_queryset(queryset, request)
    
    if page is not None:
        serializer = CompanyListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
    
    serializer = CompanyListSerializer(queryset, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def company_stats(request):
    """Get overall company statistics"""
    stats = {
        'total_companies': Company.objects.count(),
        'sponsor_companies': Company.objects.filter(is_sponsor=True).count(),
        'active_sponsors': Company.objects.filter(sponsor_status='active').count(),
        'companies_with_jobs': Company.objects.annotate(
            jobs_count=Count('jobs', filter=Q(jobs__status='active'))
        ).filter(jobs_count__gt=0).count(),
        'featured_companies': Company.objects.filter(is_featured=True).count(),
        'top_industries': list(
            Company.objects.values('industry')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        ),
        'top_locations': list(
            Company.objects.values('city', 'region')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
    }
    
    return Response(stats)


@api_view(['GET'])
def featured_companies(request):
    """Get featured companies for homepage"""
    companies = Company.objects.filter(is_featured=True).annotate(
        active_jobs_count=Count(
            'jobs',
            filter=Q(jobs__status='active')
        )
    ).order_by('-is_premium_partner', '-total_jobs_posted')[:6]
    
    serializer = CompanyListSerializer(companies, many=True)
    return Response(serializer.data)
