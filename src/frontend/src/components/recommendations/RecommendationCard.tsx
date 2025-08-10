'use client';

import { useState } from 'react';
import { JobRecommendation } from '@/types/api';
import FeedbackModal from './FeedbackModal';

interface RecommendationCardProps {
  recommendation: JobRecommendation;
  onClick: () => void;
  onFeedback: (feedback: {
    feedback: 'helpful' | 'not_helpful' | 'not_interested' | 'already_applied';
    feedback_notes?: string;
  }) => void;
}

export default function RecommendationCard({ 
  recommendation, 
  onClick, 
  onFeedback 
}: RecommendationCardProps) {
  const [showFeedback, setShowFeedback] = useState(false);
  const { job, match_score_percentage, match_reasons, score_breakdown } = recommendation;

  const getMatchColor = (score: number) => {
    if (score >= 80) return 'text-green-600 bg-green-100';
    if (score >= 60) return 'text-blue-600 bg-blue-100';
    if (score >= 40) return 'text-yellow-600 bg-yellow-100';
    return 'text-red-600 bg-red-100';
  };

  const formatSalary = (min?: number | null, max?: number | null, currency = 'GBP') => {
    const symbol = currency === 'GBP' ? '£' : currency === 'USD' ? '$' : '€';
    if (min && max) {
      return `${symbol}${min.toLocaleString()} - ${symbol}${max.toLocaleString()}`;
    }
    if (min) {
      return `${symbol}${min.toLocaleString()}+`;
    }
    return 'Competitive';
  };

  const handleFeedbackSubmit = (feedback: {
    feedback: 'helpful' | 'not_helpful' | 'not_interested' | 'already_applied';
    feedback_notes?: string;
  }) => {
    onFeedback(feedback);
    setShowFeedback(false);
  };

  return (
    <>
      <div className="bg-white rounded-lg border border-gray-200 hover:border-blue-300 transition-all duration-200 hover:shadow-lg">
        {/* Header with match score */}
        <div className="flex justify-between items-start p-6 pb-4">
          <div className="flex-1">
            <div className="flex items-start justify-between mb-2">
              <h3 className="text-xl font-semibold text-gray-900 hover:text-blue-600 cursor-pointer" onClick={onClick}>
                {job.title}
              </h3>
              <div className={`px-3 py-1 rounded-full text-sm font-medium ${getMatchColor(match_score_percentage)}`}>
                {match_score_percentage}% match
              </div>
            </div>
            
            <div className="flex items-center text-gray-600 mb-3">
              <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-4m-5 0H3m2 0h4M9 7h6m-6 4h6m-6 4h6" />
              </svg>
              <span className="font-medium hover:text-blue-600 cursor-pointer" onClick={onClick}>
                {job.company.name}
              </span>
              {job.company.is_sponsor && (
                <span className="ml-2 px-2 py-1 bg-green-100 text-green-800 text-xs rounded-full">
                  Sponsor
                </span>
              )}
            </div>

            <div className="flex flex-wrap gap-4 text-sm text-gray-600 mb-4">
              <div className="flex items-center">
                <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                {job.location}
                {job.location_type !== 'on_site' && (
                  <span className="ml-1 capitalize">({job.location_type.replace('_', ' ')})</span>
                )}
              </div>
              
              <div className="flex items-center">
                <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1" />
                </svg>
                {formatSalary(job.salary_min, job.salary_max, job.currency)}
              </div>

              <div className="flex items-center">
                <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2-2v2m8 0V6a2 2 0 012 2v6a2 2 0 01-2 2H8a2 2 0 01-2-2V8a2 2 0 012-2h8a2 2 0 012 2z" />
                </svg>
                {job.job_type.replace('_', ' ')} • {job.experience_level}
              </div>
            </div>
          </div>
        </div>

        {/* Match reasons */}
        {match_reasons && match_reasons.length > 0 && (
          <div className="px-6 pb-4">
            <h4 className="text-sm font-medium text-gray-700 mb-2">Why this job matches:</h4>
            <div className="flex flex-wrap gap-2">
              {match_reasons.slice(0, 4).map((reason, index) => (
                <span
                  key={index}
                  className="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded-full"
                >
                  {reason}
                </span>
              ))}
              {match_reasons.length > 4 && (
                <span className="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded-full">
                  +{match_reasons.length - 4} more
                </span>
              )}
            </div>
          </div>
        )}

        {/* Score breakdown */}
        {score_breakdown && (
          <div className="px-6 pb-4">
            <h4 className="text-sm font-medium text-gray-700 mb-2">Match breakdown:</h4>
            <div className="grid grid-cols-5 gap-2 text-xs">
              {Object.entries(score_breakdown).map(([category, score]) => (
                <div key={category} className="text-center">
                  <div className="font-medium text-gray-900">{score}%</div>
                  <div className="text-gray-500 capitalize">{category}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Skills */}
        {job.skills_required && job.skills_required.length > 0 && (
          <div className="px-6 pb-4">
            <h4 className="text-sm font-medium text-gray-700 mb-2">Required skills:</h4>
            <div className="flex flex-wrap gap-1">
              {job.skills_required.slice(0, 6).map((skill, index) => (
                <span
                  key={index}
                  className="px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded"
                >
                  {skill}
                </span>
              ))}
              {job.skills_required.length > 6 && (
                <span className="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded">
                  +{job.skills_required.length - 6} more
                </span>
              )}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="px-6 py-4 bg-gray-50 rounded-b-lg border-t border-gray-100">
          <div className="flex justify-between items-center">
            <div className="flex space-x-2 text-xs text-gray-500">
              {recommendation.viewed && (
                <span className="flex items-center">
                  <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M10 12a2 2 0 100-4 2 2 0 000 4z" />
                    <path fillRule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clipRule="evenodd" />
                  </svg>
                  Viewed
                </span>
              )}
              {recommendation.clicked && (
                <span className="flex items-center">
                  <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M12.293 5.293a1 1 0 011.414 0l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-2.293-2.293a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                  Clicked
                </span>
              )}
              {recommendation.applied && (
                <span className="flex items-center">
                  <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                  Applied
                </span>
              )}
            </div>

            <div className="flex space-x-2">
              <button
                onClick={() => setShowFeedback(true)}
                className="px-3 py-1 text-sm text-gray-600 hover:text-gray-900 transition-colors"
              >
                {recommendation.feedback ? 'Update feedback' : 'Give feedback'}
              </button>
              
              <button
                onClick={onClick}
                className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 transition-colors"
              >
                View Job
              </button>
            </div>
          </div>

          {/* Show existing feedback */}
          {recommendation.feedback && (
            <div className="mt-2 p-2 bg-blue-50 rounded text-xs">
              <span className="font-medium">Your feedback:</span> {recommendation.feedback.replace('_', ' ')}
              {recommendation.feedback_notes && (
                <span> - {recommendation.feedback_notes}</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Feedback Modal */}
      {showFeedback && (
        <FeedbackModal
          onSubmit={handleFeedbackSubmit}
          onClose={() => setShowFeedback(false)}
          existingFeedback={recommendation.feedback}
          existingNotes={recommendation.feedback_notes}
        />
      )}
    </>
  );
}