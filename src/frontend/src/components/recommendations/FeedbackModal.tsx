'use client';

import { useState, useEffect } from 'react';

interface FeedbackModalProps {
  onSubmit: (feedback: {
    feedback: 'helpful' | 'not_helpful' | 'not_interested' | 'already_applied';
    feedback_notes?: string;
  }) => void;
  onClose: () => void;
  existingFeedback?: string;
  existingNotes?: string;
}

export default function FeedbackModal({ 
  onSubmit, 
  onClose, 
  existingFeedback, 
  existingNotes 
}: FeedbackModalProps) {
  const [selectedFeedback, setSelectedFeedback] = useState<
    'helpful' | 'not_helpful' | 'not_interested' | 'already_applied' | ''
  >(existingFeedback as any || '');
  const [notes, setNotes] = useState(existingNotes || '');

  const feedbackOptions = [
    {
      value: 'helpful',
      label: 'Helpful recommendation',
      description: 'This job matches my preferences well',
      icon: '👍',
      color: 'text-green-600 border-green-300'
    },
    {
      value: 'not_helpful',
      label: 'Not helpful',
      description: 'This job doesn\'t match what I\'m looking for',
      icon: '👎',
      color: 'text-red-600 border-red-300'
    },
    {
      value: 'not_interested',
      label: 'Not interested',
      description: 'I\'m not interested in this type of role',
      icon: '❌',
      color: 'text-orange-600 border-orange-300'
    },
    {
      value: 'already_applied',
      label: 'Already applied',
      description: 'I\'ve already applied to this position',
      icon: '✅',
      color: 'text-blue-600 border-blue-300'
    }
  ] as const;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedFeedback) {
      onSubmit({
        feedback: selectedFeedback,
        feedback_notes: notes.trim() || undefined
      });
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg max-w-md w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-medium text-gray-900">
              Recommendation Feedback
            </h3>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 transition-colors"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-3">
                How was this recommendation?
              </label>
              <div className="space-y-2">
                {feedbackOptions.map((option) => (
                  <label
                    key={option.value}
                    className={`flex items-start p-3 border rounded-lg cursor-pointer transition-colors ${
                      selectedFeedback === option.value
                        ? `${option.color} bg-opacity-5`
                        : 'border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <input
                      type="radio"
                      name="feedback"
                      value={option.value}
                      checked={selectedFeedback === option.value}
                      onChange={(e) => setSelectedFeedback(e.target.value as any)}
                      className="sr-only"
                    />
                    <div className="flex-shrink-0 text-lg mr-3">
                      {option.icon}
                    </div>
                    <div>
                      <div className="font-medium text-gray-900">
                        {option.label}
                      </div>
                      <div className="text-sm text-gray-500">
                        {option.description}
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div className="mb-6">
              <label htmlFor="notes" className="block text-sm font-medium text-gray-700 mb-2">
                Additional comments (optional)
              </label>
              <textarea
                id="notes"
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Tell us more about why this recommendation was or wasn't helpful..."
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                maxLength={500}
              />
              <div className="text-xs text-gray-500 mt-1">
                {notes.length}/500 characters
              </div>
            </div>

            <div className="flex justify-end space-x-3">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 border border-gray-300 rounded-md hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!selectedFeedback}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                Submit Feedback
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}