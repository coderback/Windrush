from django.urls import path
from . import views

app_name = 'companies'

urlpatterns = [
    # Company management
    path('', views.CompanyListCreateView.as_view(), name='company_list_create'),
    path('<slug:slug>/', views.CompanyDetailView.as_view(), name='company_detail'),
    
    # Company reviews
    path('<slug:company_slug>/reviews/', views.CompanyReviewListCreateView.as_view(), name='company_reviews'),
    path('reviews/<int:review_id>/helpful/', views.mark_review_helpful, name='mark_review_helpful'),
    
    # Search and filtering
    path('search/', views.company_search, name='company_search'),
    
    # Statistics and featured companies
    path('stats/', views.company_stats, name='company_stats'),
    path('featured/', views.featured_companies, name='featured_companies'),
]