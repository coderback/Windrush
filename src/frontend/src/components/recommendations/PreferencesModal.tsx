'use client';

import { useState } from 'react';
import { UserJobPreference } from '@/types/api';

interface PreferencesModalProps {
  preferences: UserJobPreference;
  onSave: (preferences: Partial<UserJobPreference>) => void;
  onClose: () => void;
}

export default function PreferencesModal({ 
  preferences, 
  onSave, 
  onClose 
}: PreferencesModalProps) {
  const [formData, setFormData] = useState({
    preferred_locations: preferences.preferred_locations.join(', '),
    max_commute_distance: preferences.max_commute_distance || '',
    open_to_remote: preferences.open_to_remote,
    open_to_hybrid: preferences.open_to_hybrid,
    preferred_job_types: preferences.preferred_job_types.join(', '),
    preferred_industries: preferences.preferred_industries.join(', '),
    experience_level: preferences.experience_level,
    min_salary: preferences.min_salary || '',
    max_salary: preferences.max_salary || '',
    salary_currency: preferences.salary_currency,
    key_skills: preferences.key_skills.join(', '),
    avoid_keywords: preferences.avoid_keywords.join(', '),
    preferred_company_sizes: preferences.preferred_company_sizes.join(', '),
    requires_sponsorship: preferences.requires_sponsorship,
    visa_types_needed: preferences.visa_types_needed.join(', '),
    notification_frequency: preferences.notification_frequency,
    max_recommendations: preferences.max_recommendations,
  });

  const [activeTab, setActiveTab] = useState<'location' | 'job' | 'company' | 'preferences'>('location');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    const updatedPreferences: Partial<UserJobPreference> = {
      preferred_locations: formData.preferred_locations.split(',').map(s => s.trim()).filter(Boolean),
      max_commute_distance: formData.max_commute_distance ? parseInt(formData.max_commute_distance.toString()) : undefined,
      open_to_remote: formData.open_to_remote,
      open_to_hybrid: formData.open_to_hybrid,
      preferred_job_types: formData.preferred_job_types.split(',').map(s => s.trim()).filter(Boolean),
      preferred_industries: formData.preferred_industries.split(',').map(s => s.trim()).filter(Boolean),
      experience_level: formData.experience_level,
      min_salary: formData.min_salary ? parseInt(formData.min_salary.toString()) : undefined,
      max_salary: formData.max_salary ? parseInt(formData.max_salary.toString()) : undefined,
      salary_currency: formData.salary_currency,
      key_skills: formData.key_skills.split(',').map(s => s.trim()).filter(Boolean),
      avoid_keywords: formData.avoid_keywords.split(',').map(s => s.trim()).filter(Boolean),
      preferred_company_sizes: formData.preferred_company_sizes.split(',').map(s => s.trim()).filter(Boolean),
      requires_sponsorship: formData.requires_sponsorship,
      visa_types_needed: formData.visa_types_needed.split(',').map(s => s.trim()).filter(Boolean),
      notification_frequency: formData.notification_frequency,
      max_recommendations: formData.max_recommendations,
    };

    onSave(updatedPreferences);
  };

  const updateField = (field: string, value: any) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const tabs = [
    { key: 'location', label: 'Location & Remote', icon: '📍' },
    { key: 'job', label: 'Job Details', icon: '💼' },
    { key: 'company', label: 'Company & Skills', icon: '🏢' },
    { key: 'preferences', label: 'Preferences', icon: '⚙️' }
  ] as const;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg max-w-4xl w-full max-h-[90vh] overflow-hidden">
        <div className="flex h-full">
          {/* Sidebar */}
          <div className="w-64 bg-gray-50 border-r border-gray-200 p-4">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-lg font-medium text-gray-900">
                Job Preferences
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

            <nav className="space-y-2">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`w-full text-left p-3 rounded-lg transition-colors ${
                    activeTab === tab.key
                      ? 'bg-blue-100 text-blue-700 border border-blue-200'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  <div className="flex items-center">
                    <span className="text-lg mr-3">{tab.icon}</span>
                    <span className="font-medium">{tab.label}</span>
                  </div>
                </button>
              ))}
            </nav>
          </div>

          {/* Content */}
          <div className="flex-1 flex flex-col">
            <div className="flex-1 overflow-y-auto p-6">
              <form onSubmit={handleSubmit}>
                {activeTab === 'location' && (
                  <div className="space-y-6">
                    <h4 className="text-lg font-medium text-gray-900 mb-4">Location & Work Style</h4>
                    
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Preferred Locations
                      </label>
                      <input
                        type="text"
                        value={formData.preferred_locations}
                        onChange={(e) => updateField('preferred_locations', e.target.value)}
                        placeholder="London, Manchester, Birmingham (comma-separated)"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <p className="text-xs text-gray-500 mt-1">Enter cities or regions separated by commas</p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Max Commute Distance (miles)
                      </label>
                      <input
                        type="number"
                        value={formData.max_commute_distance}
                        onChange={(e) => updateField('max_commute_distance', e.target.value)}
                        placeholder="25"
                        min="0"
                        max="100"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>

                    <div className="space-y-3">
                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={formData.open_to_remote}
                          onChange={(e) => updateField('open_to_remote', e.target.checked)}
                          className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                        />
                        <span className="ml-2 text-sm text-gray-700">Open to remote work</span>
                      </label>

                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={formData.open_to_hybrid}
                          onChange={(e) => updateField('open_to_hybrid', e.target.checked)}
                          className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                        />
                        <span className="ml-2 text-sm text-gray-700">Open to hybrid work</span>
                      </label>
                    </div>
                  </div>
                )}

                {activeTab === 'job' && (
                  <div className="space-y-6">
                    <h4 className="text-lg font-medium text-gray-900 mb-4">Job Details</h4>
                    
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Preferred Job Types
                      </label>
                      <input
                        type="text"
                        value={formData.preferred_job_types}
                        onChange={(e) => updateField('preferred_job_types', e.target.value)}
                        placeholder="Software Engineering, Data Science, Product Management"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Preferred Industries
                      </label>
                      <input
                        type="text"
                        value={formData.preferred_industries}
                        onChange={(e) => updateField('preferred_industries', e.target.value)}
                        placeholder="Technology, Finance, Healthcare"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Experience Level
                      </label>
                      <select
                        value={formData.experience_level}
                        onChange={(e) => updateField('experience_level', e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="entry">Entry Level</option>
                        <option value="mid">Mid Level</option>
                        <option value="senior">Senior Level</option>
                        <option value="lead">Lead/Principal</option>
                        <option value="executive">Executive</option>
                      </select>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Minimum Salary
                        </label>
                        <input
                          type="number"
                          value={formData.min_salary}
                          onChange={(e) => updateField('min_salary', e.target.value)}
                          placeholder="50000"
                          min="0"
                          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Maximum Salary
                        </label>
                        <input
                          type="number"
                          value={formData.max_salary}
                          onChange={(e) => updateField('max_salary', e.target.value)}
                          placeholder="100000"
                          min="0"
                          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Currency
                      </label>
                      <select
                        value={formData.salary_currency}
                        onChange={(e) => updateField('salary_currency', e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="GBP">GBP (£)</option>
                        <option value="USD">USD ($)</option>
                        <option value="EUR">EUR (€)</option>
                      </select>
                    </div>
                  </div>
                )}

                {activeTab === 'company' && (
                  <div className="space-y-6">
                    <h4 className="text-lg font-medium text-gray-900 mb-4">Skills & Companies</h4>
                    
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Key Skills
                      </label>
                      <textarea
                        rows={3}
                        value={formData.key_skills}
                        onChange={(e) => updateField('key_skills', e.target.value)}
                        placeholder="React, TypeScript, Python, AWS, Machine Learning"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <p className="text-xs text-gray-500 mt-1">Skills you want to use or learn (comma-separated)</p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Keywords to Avoid
                      </label>
                      <input
                        type="text"
                        value={formData.avoid_keywords}
                        onChange={(e) => updateField('avoid_keywords', e.target.value)}
                        placeholder="PHP, COBOL, night shifts"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <p className="text-xs text-gray-500 mt-1">Technologies or terms you want to avoid</p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Preferred Company Sizes
                      </label>
                      <input
                        type="text"
                        value={formData.preferred_company_sizes}
                        onChange={(e) => updateField('preferred_company_sizes', e.target.value)}
                        placeholder="startup, small, medium, large"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>

                    <div className="space-y-3">
                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={formData.requires_sponsorship}
                          onChange={(e) => updateField('requires_sponsorship', e.target.checked)}
                          className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                        />
                        <span className="ml-2 text-sm text-gray-700">Requires visa sponsorship</span>
                      </label>

                      {formData.requires_sponsorship && (
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">
                            Visa Types Needed
                          </label>
                          <input
                            type="text"
                            value={formData.visa_types_needed}
                            onChange={(e) => updateField('visa_types_needed', e.target.value)}
                            placeholder="skilled_worker, global_talent"
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {activeTab === 'preferences' && (
                  <div className="space-y-6">
                    <h4 className="text-lg font-medium text-gray-900 mb-4">Notification & Settings</h4>
                    
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Notification Frequency
                      </label>
                      <select
                        value={formData.notification_frequency}
                        onChange={(e) => updateField('notification_frequency', e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="daily">Daily</option>
                        <option value="weekly">Weekly</option>
                        <option value="monthly">Monthly</option>
                        <option value="disabled">Disabled</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Maximum Recommendations per Request
                      </label>
                      <input
                        type="number"
                        value={formData.max_recommendations}
                        onChange={(e) => updateField('max_recommendations', parseInt(e.target.value))}
                        min="1"
                        max="50"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <p className="text-xs text-gray-500 mt-1">Between 1 and 50 recommendations</p>
                    </div>
                  </div>
                )}
              </form>
            </div>

            {/* Footer */}
            <div className="border-t border-gray-200 px-6 py-4">
              <div className="flex justify-end space-x-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 border border-gray-300 rounded-md hover:bg-gray-200 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSubmit}
                  className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 transition-colors"
                >
                  Save Preferences
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}