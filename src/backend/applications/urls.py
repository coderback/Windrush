from django.urls import path
from . import views

app_name = 'applications'

urlpatterns = [
    # Application management
    path('', views.ApplicationListCreateView.as_view(), name='application_list_create'),
    path('<int:pk>/', views.ApplicationDetailView.as_view(), name='application_detail'),
    
    # Job applications
    path('jobs/<int:job_id>/apply/', views.apply_to_job, name='apply_to_job'),
    path('companies/<int:company_id>/speculative/', views.submit_speculative_application, name='speculative_application'),
    
    # Application status management
    path('<int:application_id>/status/', views.update_application_status, name='update_application_status'),
    path('<int:application_id>/history/', views.ApplicationStatusHistoryView.as_view(), name='application_status_history'),
    
    # Application messaging
    path('<int:application_id>/messages/', views.ApplicationMessageListCreateView.as_view(), name='application_messages'),
    
    # Search and statistics
    path('search/', views.application_search, name='application_search'),
    path('stats/', views.application_stats, name='application_stats'),
    
    # Employer-specific endpoints
    path('employer/applications/', views.employer_applications, name='employer_applications'),
    path('employer/stats/', views.employer_application_stats, name='employer_application_stats'),
]