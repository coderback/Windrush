"""
URL configuration for windrush_api project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.conf import settings
from django.conf.urls.static import static

def api_health(request):
    return JsonResponse({
        'status': 'healthy',
        'message': 'Windrush API is running',
        'version': '0.1.0',
        'environment': 'development' if settings.DEBUG else 'production'
    })

def api_root(request):
    return JsonResponse({
        'message': 'Welcome to Windrush API',
        'version': '0.1.0',
        'endpoints': {
            'auth': '/api/auth/',
            'accounts': '/api/accounts/',
            'companies': '/api/companies/',
            'jobs': '/api/jobs/',
            'applications': '/api/applications/',
            'health': '/api/health/',
            'docs': '/api/docs/',
        }
    })

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # API endpoints
    path('api/', api_root, name='api_root'),
    path('api/health/', api_health, name='api_health'),
    
    # Authentication and accounts
    path('api/auth/', include('accounts.urls')),
    
    # Main app endpoints
    path('api/companies/', include('companies.urls')),
    path('api/jobs/', include('jobs.urls')),
    # path('api/applications/', include('applications.urls')),
    
    # Django REST framework browsable API
    path('api-auth/', include('rest_framework.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
