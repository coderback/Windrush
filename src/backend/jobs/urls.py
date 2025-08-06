from django.urls import path
from . import views

app_name = 'jobs'

urlpatterns = [
    # Job management
    path('', views.JobListCreateView.as_view(), name='job_list_create'),
    path('<slug:slug>/', views.JobDetailView.as_view(), name='job_detail'),
    
    # Search and filtering
    path('search/', views.job_search, name='job_search'),
    
    # Statistics and featured jobs
    path('stats/', views.job_stats, name='job_stats'),
    path('featured/', views.featured_jobs, name='featured_jobs'),
    
    # Saved jobs
    path('saved/', views.SavedJobsListView.as_view(), name='saved_jobs_list'),
    path('<int:job_id>/save/', views.save_job, name='save_job'),
    path('<int:job_id>/unsave/', views.unsave_job, name='unsave_job'),
    
    # Job alerts
    path('alerts/', views.JobAlertListCreateView.as_view(), name='job_alerts_list_create'),
    path('alerts/<int:pk>/', views.JobAlertDetailView.as_view(), name='job_alert_detail'),
    path('alerts/<int:alert_id>/toggle/', views.toggle_job_alert, name='toggle_job_alert'),
]