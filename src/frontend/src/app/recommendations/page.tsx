'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';
import { JobRecommendation, RecommendationStats, UserJobPreference } from '@/types/api';
import RecommendationCard from '@/components/recommendations/RecommendationCard';
import RecommendationFilters from '@/components/recommendations/RecommendationFilters';
import PreferencesModal from '@/components/recommendations/PreferencesModal';

export default function RecommendationsPage() {
  const router = useRouter();
  const [recommendations, setRecommendations] = useState<JobRecommendation[]>([]);
  const [stats, setStats] = useState<RecommendationStats | null>(null);
  const [preferences, setPreferences] = useState<UserJobPreference | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPreferences, setShowPreferences] = useState(false);

  useEffect(() => {
    loadRecommendations();
    loadStats();
    loadPreferences();
  }, []);

  const loadRecommendations = async () => {
    try {
      const response = await apiClient.getRecommendations();
      setRecommendations(response.results);
    } catch (error) {
      console.error('Failed to load recommendations:', error);
      setError('Failed to load recommendations');
    }
  };

  const loadStats = async () => {
    try {
      const statsData = await apiClient.getRecommendationStats();
      setStats(statsData);
    } catch (error) {
      console.error('Failed to load stats:', error);
    }
  };

  const loadPreferences = async () => {
    try {
      const preferencesData = await apiClient.getUserPreferences();
      setPreferences(preferencesData);
    } catch (error) {
      console.error('Failed to load preferences:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateRecommendations = async (refresh: boolean = false) => {
    setGenerating(true);
    setError(null);
    
    try {
      const response = await apiClient.generateRecommendations({
        limit: preferences?.max_recommendations || 10,
        refresh
      });
      
      if (response.recommendations && response.recommendations.length > 0) {
        setRecommendations(response.recommendations);
        await loadStats(); // Refresh stats
      } else {
        setError(response.message || 'No recommendations found');
      }
    } catch (error: any) {
      console.error('Failed to generate recommendations:', error);
      setError(error.detail || error.message || 'Failed to generate recommendations');
    } finally {
      setGenerating(false);
    }
  };

  const handleRecommendationClick = async (recommendation: JobRecommendation) => {
    try {
      // Track click
      await apiClient.clickRecommendation(recommendation.id);
      
      // Update local state
      setRecommendations(prev => 
        prev.map(rec => 
          rec.id === recommendation.id 
            ? { ...rec, clicked: true } 
            : rec
        )
      );

      // Navigate to job detail
      router.push(`/jobs/${recommendation.job.slug}`);
    } catch (error) {
      console.error('Failed to track click:', error);
      // Still navigate even if tracking fails
      router.push(`/jobs/${recommendation.job.slug}`);
    }
  };

  const handleFeedback = async (recommendationId: number, feedback: {
    feedback: 'helpful' | 'not_helpful' | 'not_interested' | 'already_applied';
    feedback_notes?: string;
  }) => {
    try {
      await apiClient.submitRecommendationFeedback(recommendationId, feedback);
      
      // Update local state
      setRecommendations(prev => 
        prev.map(rec => 
          rec.id === recommendationId 
            ? { ...rec, feedback: feedback.feedback, feedback_notes: feedback.feedback_notes } 
            : rec
        )
      );
    } catch (error) {
      console.error('Failed to submit feedback:', error);
    }
  };

  const handlePreferencesSave = async (newPreferences: Partial<UserJobPreference>) => {
    try {
      const updated = await apiClient.updateUserPreferences(newPreferences);
      setPreferences(updated);
      setShowPreferences(false);
      
      // Auto-generate fresh recommendations after preferences change
      await handleGenerateRecommendations(true);
    } catch (error) {
      console.error('Failed to update preferences:', error);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h1 className="text-3xl font-bold text-gray-900 mb-2">
                Job Recommendations
              </h1>
              <p className="text-gray-600">
                Personalized job matches based on your preferences and profile
              </p>
            </div>
            
            <div className="flex gap-3">
              <button
                onClick={() => setShowPreferences(true)}
                className="px-4 py-2 border border-gray-300 rounded-md text-gray-700 bg-white hover:bg-gray-50 transition-colors"
              >
                Edit Preferences
              </button>
              
              <button
                onClick={() => handleGenerateRecommendations(true)}
                disabled={generating}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {generating ? 'Generating...' : 'Refresh Recommendations'}
              </button>
            </div>
          </div>

          {/* Stats */}
          {stats && (
            <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mb-6">
              <div className="bg-white p-4 rounded-lg border">
                <div className="text-2xl font-bold text-blue-600">{stats.total_recommendations}</div>
                <div className="text-sm text-gray-600">Total Recommendations</div>
              </div>
              <div className="bg-white p-4 rounded-lg border">
                <div className="text-2xl font-bold text-green-600">{stats.average_score}%</div>
                <div className="text-sm text-gray-600">Average Match</div>
              </div>
              <div className="bg-white p-4 rounded-lg border">
                <div className="text-2xl font-bold text-purple-600">{stats.viewed_count}</div>
                <div className="text-sm text-gray-600">Viewed</div>
              </div>
              <div className="bg-white p-4 rounded-lg border">
                <div className="text-2xl font-bold text-orange-600">{stats.clicked_count}</div>
                <div className="text-sm text-gray-600">Clicked</div>
              </div>
              <div className="bg-white p-4 rounded-lg border">
                <div className="text-2xl font-bold text-red-600">{stats.applied_count}</div>
                <div className="text-sm text-gray-600">Applied</div>
              </div>
            </div>
          )}
        </div>

        {/* Error Message */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-md">
            <div className="flex">
              <div className="text-red-800">
                <p className="font-medium">Error</p>
                <p className="text-sm">{error}</p>
              </div>
            </div>
          </div>
        )}

        {/* No Recommendations State */}
        {recommendations.length === 0 && !loading && !generating && (
          <div className="text-center py-12">
            <div className="max-w-md mx-auto">
              <div className="mb-4">
                <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-2">No Recommendations Yet</h3>
              <p className="text-gray-500 mb-6">
                We haven't generated any job recommendations for you yet. 
                Set your preferences and generate recommendations to get started.
              </p>
              <button
                onClick={() => handleGenerateRecommendations()}
                disabled={generating}
                className="inline-flex items-center px-4 py-2 border border-transparent text-base font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50"
              >
                {generating ? 'Generating...' : 'Generate Recommendations'}
              </button>
            </div>
          </div>
        )}

        {/* Recommendations List */}
        {recommendations.length > 0 && (
          <div className="space-y-6">
            {recommendations.map((recommendation) => (
              <RecommendationCard
                key={recommendation.id}
                recommendation={recommendation}
                onClick={() => handleRecommendationClick(recommendation)}
                onFeedback={(feedback) => handleFeedback(recommendation.id, feedback)}
              />
            ))}
          </div>
        )}

        {/* Preferences Modal */}
        {showPreferences && preferences && (
          <PreferencesModal
            preferences={preferences}
            onSave={handlePreferencesSave}
            onClose={() => setShowPreferences(false)}
          />
        )}
      </div>
    </div>
  );
}