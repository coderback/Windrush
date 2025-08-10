from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserJobPreferenceViewSet, JobRecommendationViewSet

router = DefaultRouter()
router.register(r"preferences", UserJobPreferenceViewSet, basename="user-job-preferences")
router.register(r"recommendations", JobRecommendationViewSet, basename="job-recommendations")

urlpatterns = [
    path("api/", include(router.urls)),
]
