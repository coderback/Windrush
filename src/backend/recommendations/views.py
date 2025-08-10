from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
from .models import UserJobPreference, JobRecommendation, RecommendationBatch
from .serializers import (
    UserJobPreferenceSerializer,
    JobRecommendationListSerializer,
    JobRecommendationDetailSerializer,
    RecommendationFeedbackSerializer,
    GenerateRecommendationsSerializer
)
from .engine import JobRecommendationEngine
import logging

logger = logging.getLogger(__name__)


class UserJobPreferenceViewSet(viewsets.ModelViewSet):
    """ViewSet for managing user job preferences"""
    serializer_class = UserJobPreferenceSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return UserJobPreference.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=False, methods=["get"])
    def current(self):
        """Get current user's preferences"""
        preferences, created = UserJobPreference.objects.get_or_create(
            user=self.request.user
        )
        serializer = self.get_serializer(preferences)
        return Response(serializer.data)
    
    @action(detail=False, methods=["post", "put", "patch"])
    def update_preferences(self):
        """Update user preferences (create if doesn't exist)"""
        preferences, created = UserJobPreference.objects.get_or_create(
            user=self.request.user
        )
        
        serializer = self.get_serializer(
            preferences, 
            data=self.request.data,
            partial=self.request.method in ["PATCH"]
        )
        
        if serializer.is_valid():
            serializer.save()
            
            # Generate fresh recommendations when preferences change
            engine = JobRecommendationEngine()
            try:
                recommendations = engine.generate_recommendations(
                    user=self.request.user,
                    limit=preferences.max_recommendations,
                    refresh=True
                )
                logger.info(f"Generated {len(recommendations)} fresh recommendations after preferences update")
            except Exception as e:
                logger.error(f"Failed to generate recommendations after preferences update: {e}")
            
            return Response(serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class JobRecommendationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for job recommendations"""
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return JobRecommendation.objects.filter(
            user=self.request.user
        ).select_related("job", "job__company").order_by("-match_score", "-created_at")
    
    def get_serializer_class(self):
        if self.action == "retrieve":
            return JobRecommendationDetailSerializer
        return JobRecommendationListSerializer
    
    def retrieve(self, request, *args, **kwargs):
        """Get detailed recommendation and mark as viewed"""
        recommendation = self.get_object()
        recommendation.mark_viewed()
        
        serializer = self.get_serializer(recommendation)
        return Response(serializer.data)
    
    @action(detail=True, methods=["post"])
    def click(self, request, pk=None):
        """Mark recommendation as clicked"""
        recommendation = self.get_object()
        recommendation.mark_clicked()
        
        return Response({"status": "clicked"})
    
    @action(detail=True, methods=["post"])
    def feedback(self, request, pk=None):
        """Submit feedback for a recommendation"""
        recommendation = self.get_object()
        serializer = RecommendationFeedbackSerializer(
            recommendation,
            data=request.data,
            partial=True
        )
        
        if serializer.is_valid():
            serializer.save(feedback_at=timezone.now())
            return Response({"status": "feedback_saved"})
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=["post"])
    def generate(self, request):
        """Generate new recommendations for user"""
        serializer = GenerateRecommendationsSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        limit = serializer.validated_data["limit"]
        refresh = serializer.validated_data["refresh"]
        
        try:
            engine = JobRecommendationEngine()
            recommendations = engine.generate_recommendations(
                user=request.user,
                limit=limit,
                refresh=refresh
            )
            
            if not recommendations:
                return Response({
                    "message": "No recommendations found. Try updating your preferences.",
                    "recommendations": []
                })
            
            # Serialize the recommendations
            serializer = JobRecommendationListSerializer(recommendations, many=True)
            
            return Response({
                "message": f"Generated {len(recommendations)} recommendations",
                "count": len(recommendations),
                "recommendations": serializer.data
            })
            
        except Exception as e:
            logger.error(f"Failed to generate recommendations for {request.user.email}: {e}")
            return Response(
                {"error": "Failed to generate recommendations. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Get recommendation statistics for user"""
        recommendations = self.get_queryset()
        
        stats = {
            "total_recommendations": recommendations.count(),
            "viewed_count": recommendations.filter(viewed=True).count(),
            "clicked_count": recommendations.filter(clicked=True).count(),
            "applied_count": recommendations.filter(applied=True).count(),
            "feedback_count": recommendations.exclude(feedback__isnull=True).count(),
        }
        
        if recommendations.exists():
            stats["average_score"] = round(
                sum(r.match_score for r in recommendations) / recommendations.count() * 100,
                1
            )
            
            # Get recent batch info
            recent_batch = RecommendationBatch.objects.filter(
                user=request.user
            ).order_by("-created_at").first()
            
            if recent_batch:
                stats["last_generated"] = recent_batch.created_at
                stats["generation_time_ms"] = recent_batch.generation_time_ms
        else:
            stats["average_score"] = 0
            stats["last_generated"] = None
            stats["generation_time_ms"] = 0
        
        return Response(stats)
    
    @action(detail=False, methods=["delete"])
    def clear(self, request):
        """Clear old recommendations for user"""
        cutoff_date = timezone.now() - timezone.timedelta(days=30)
        deleted_count, _ = JobRecommendation.objects.filter(
            user=request.user,
            created_at__lt=cutoff_date
        ).delete()
        
        return Response({
            "message": f"Cleared {deleted_count} old recommendations"
        })
