'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { apiClient } from '@/lib/api';
import { Job } from '@/types/api';
import { useAuth } from '@/contexts/AuthContext';

export default function JobDetailPage() {
  const params = useParams();
  const { isAuthenticated, user } = useAuth();
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [showApplicationForm, setShowApplicationForm] = useState(false);
  const [applicationData, setApplicationData] = useState({
    cover_letter: '',
    requires_sponsorship: true,
    expected_salary: '',
    available_start_date: '',
  });

  useEffect(() => {
    if (params.slug) {
      fetchJob();
    }
  }, [params.slug]);

  const fetchJob = async () => {
    try {
      setLoading(true);
      const jobData = await apiClient.getJob(params.slug as string);
      setJob(jobData);
      setError(null);
    } catch (err) {
      setError('Job not found or failed to load');
      console.error('Error fetching job:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleApply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!job || !isAuthenticated) return;

    try {
      setApplying(true);
      
      const applicationPayload = {
        ...applicationData,
        expected_salary: applicationData.expected_salary ? parseInt(applicationData.expected_salary) : undefined,
      };

      await apiClient.applyToJob(job.id, applicationPayload);
      
      // Show success message
      alert('Application submitted successfully! You can track its progress in your dashboard.');
      setShowApplicationForm(false);
      
    } catch (err: any) {
      alert(err.message || 'Failed to submit application. Please try again.');
    } finally {
      setApplying(false);
    }
  };

  const formatSalary = (job: Job) => {
    if (job.salary_min && job.salary_max) {
      return `£${job.salary_min.toLocaleString()} - £${job.salary_max.toLocaleString()}`;
    } else if (job.salary_min) {
      return `£${job.salary_min.toLocaleString()}+`;
    } else if (job.salary_max) {
      return `Up to £${job.salary_max.toLocaleString()}`;
    }
    return 'Salary not specified';
  };

  const formatJobType = (jobType: string) => {
    return jobType.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  const formatExperienceLevel = (level: string) => {
    const levels: { [key: string]: string } = {
      'entry': 'Entry Level (0-2 years)',
      'junior': 'Junior (1-3 years)',
      'mid': 'Mid Level (3-5 years)',
      'senior': 'Senior (5+ years)',
      'lead': 'Lead/Principal (7+ years)',
      'executive': 'Executive (10+ years)'
    };
    return levels[level] || level;
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-4">Job Not Found</h1>
          <p className="text-gray-600 mb-4">The job you're looking for doesn't exist or has been removed.</p>
          <Link href="/jobs" className="text-blue-600 hover:text-blue-800 font-medium">
            ← Back to Job Listings
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <Link href="/jobs" className="text-blue-600 hover:text-blue-800 font-medium mb-4 inline-block">
            ← Back to Job Listings
          </Link>
          
          <div className="flex justify-between items-start mb-4">
            <div className="flex-1">
              <div className="flex items-center space-x-2 mb-2">
                <h1 className="text-3xl font-bold text-gray-900">{job.title}</h1>
                {job.is_featured && (
                  <span className="px-2 py-1 bg-yellow-100 text-yellow-800 text-sm font-medium rounded-full">
                    Featured
                  </span>
                )}
                {job.is_urgent && (
                  <span className="px-2 py-1 bg-red-100 text-red-800 text-sm font-medium rounded-full">
                    Urgent
                  </span>
                )}
              </div>
              <Link
                href={`/companies/${job.company.slug}`}
                className="text-xl text-blue-600 hover:text-blue-800 font-medium"
              >
                {job.company.name}
              </Link>
            </div>
            
            <div className="text-right">
              <div className="text-2xl font-bold text-gray-900">
                {formatSalary(job)}
              </div>
              <div className="text-gray-500">per year</div>
            </div>
          </div>

          {/* Key Info */}
          <div className="flex flex-wrap items-center gap-6 text-gray-600">
            <div className="flex items-center">
              <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              {job.location}
            </div>
            <div className="flex items-center">
              <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m8 0V6a2 2 0 00-2 2H8a2 2 0 00-2-2V6m8 0h2a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h2" />
              </svg>
              {formatJobType(job.job_type)}
            </div>
            <div className="flex items-center">
              <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
              {formatExperienceLevel(job.experience_level)}
            </div>
            <div className="flex items-center">
              <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Posted {job.days_since_posted === 0 ? 'today' : 
                      job.days_since_posted === 1 ? '1 day ago' :
                      `${job.days_since_posted} days ago`}
            </div>
          </div>

          {/* Visa Sponsorship Badge */}
          {job.visa_sponsorship_available && (
            <div className="mt-4">
              <div className="inline-flex items-center px-3 py-1 bg-green-100 text-green-800 rounded-full font-medium">
                <svg className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Visa Sponsorship Available
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Job Details */}
          <div className="lg:col-span-2">
            <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
              <h2 className="text-2xl font-bold text-gray-900 mb-4">Job Description</h2>
              <div 
                className="prose max-w-none text-gray-700"
                dangerouslySetInnerHTML={{ __html: job.description }}
              />
            </div>

            <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
              <h2 className="text-2xl font-bold text-gray-900 mb-4">Requirements</h2>
              <div 
                className="prose max-w-none text-gray-700"
                dangerouslySetInnerHTML={{ __html: job.requirements }}
              />
            </div>

            {job.benefits && job.benefits.length > 0 && (
              <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
                <h2 className="text-2xl font-bold text-gray-900 mb-4">Benefits</h2>
                <ul className="space-y-2">
                  {job.benefits.map((benefit, index) => (
                    <li key={index} className="flex items-center text-gray-700">
                      <svg className="h-4 w-4 mr-2 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      {benefit}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {job.skills_required && job.skills_required.length > 0 && (
              <div className="bg-white rounded-lg shadow-sm p-6">
                <h2 className="text-2xl font-bold text-gray-900 mb-4">Required Skills</h2>
                <div className="flex flex-wrap gap-2">
                  {job.skills_required.map((skill, index) => (
                    <span
                      key={index}
                      className="px-3 py-1 bg-blue-100 text-blue-800 font-medium rounded-full"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div className="lg:col-span-1">
            <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Job Details</h3>
              <div className="space-y-3">
                <div>
                  <span className="text-sm text-gray-500">Application Deadline:</span>
                  <div className="text-gray-900">
                    {job.application_deadline 
                      ? new Date(job.application_deadline).toLocaleDateString()
                      : 'No deadline specified'
                    }
                  </div>
                </div>
                <div>
                  <span className="text-sm text-gray-500">Applications:</span>
                  <div className="text-gray-900">{job.application_count} candidates</div>
                </div>
                <div>
                  <span className="text-sm text-gray-500">Location Type:</span>
                  <div className="text-gray-900 capitalize">
                    {job.location_type.replace('_', ' ')}
                  </div>
                </div>
                {job.visa_types_supported && job.visa_types_supported.length > 0 && (
                  <div>
                    <span className="text-sm text-gray-500">Visa Types Supported:</span>
                    <div className="text-gray-900">
                      {job.visa_types_supported.map((type, index) => (
                        <span key={index} className="block capitalize">
                          {type.replace('_', ' ')}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Apply Button */}
            {isAuthenticated ? (
              user?.user_type === 'job_seeker' ? (
                <div className="bg-white rounded-lg shadow-sm p-6">
                  {!showApplicationForm ? (
                    <button
                      onClick={() => setShowApplicationForm(true)}
                      className="w-full px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
                    >
                      Apply for This Job
                    </button>
                  ) : (
                    <div>
                      <h3 className="text-lg font-semibold text-gray-900 mb-4">Apply for This Job</h3>
                      <form onSubmit={handleApply} className="space-y-4">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Cover Letter *
                          </label>
                          <textarea
                            required
                            value={applicationData.cover_letter}
                            onChange={(e) => setApplicationData(prev => ({ ...prev, cover_letter: e.target.value }))}
                            rows={6}
                            placeholder="Tell us why you're interested in this role and what makes you a great fit..."
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                          <p className="text-xs text-gray-500 mt-1">Minimum 50 characters</p>
                        </div>

                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Expected Salary (£)
                          </label>
                          <input
                            type="number"
                            value={applicationData.expected_salary}
                            onChange={(e) => setApplicationData(prev => ({ ...prev, expected_salary: e.target.value }))}
                            placeholder="e.g. 35000"
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>

                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Available Start Date
                          </label>
                          <input
                            type="date"
                            value={applicationData.available_start_date}
                            onChange={(e) => setApplicationData(prev => ({ ...prev, available_start_date: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>

                        <div className="flex items-center">
                          <input
                            type="checkbox"
                            id="requires_sponsorship"
                            checked={applicationData.requires_sponsorship}
                            onChange={(e) => setApplicationData(prev => ({ ...prev, requires_sponsorship: e.target.checked }))}
                            className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                          />
                          <label htmlFor="requires_sponsorship" className="ml-2 text-sm text-gray-700">
                            I require visa sponsorship
                          </label>
                        </div>

                        <div className="flex space-x-3">
                          <button
                            type="submit"
                            disabled={applying}
                            className="flex-1 px-4 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {applying ? 'Submitting...' : 'Submit Application'}
                          </button>
                          <button
                            type="button"
                            onClick={() => setShowApplicationForm(false)}
                            className="px-4 py-2 border border-gray-300 text-gray-700 font-medium rounded-md hover:bg-gray-50"
                          >
                            Cancel
                          </button>
                        </div>
                      </form>
                    </div>
                  )}
                </div>
              ) : (
                <div className="bg-white rounded-lg shadow-sm p-6">
                  <p className="text-gray-600 text-center">
                    Only job seekers can apply for jobs.
                  </p>
                </div>
              )
            ) : (
              <div className="bg-white rounded-lg shadow-sm p-6">
                <p className="text-gray-600 mb-4 text-center">
                  Sign in to apply for this job
                </p>
                <Link
                  href="/auth/login"
                  className="block w-full px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 text-center transition-colors"
                >
                  Sign In to Apply
                </Link>
              </div>
            )}

            {/* Company Info */}
            <div className="bg-white rounded-lg shadow-sm p-6 mt-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">About {job.company.name}</h3>
              <div className="space-y-3 text-sm">
                <div>
                  <span className="text-gray-500">Industry:</span>
                  <div className="text-gray-900">{job.company.industry}</div>
                </div>
                <div>
                  <span className="text-gray-500">Company Size:</span>
                  <div className="text-gray-900 capitalize">
                    {job.company.company_size.replace(/_/g, ' ')}
                  </div>
                </div>
                <div>
                  <span className="text-gray-500">Location:</span>
                  <div className="text-gray-900">{job.company.city}, {job.company.region}</div>
                </div>
                {job.company.is_sponsor && (
                  <div className="flex items-center text-green-600">
                    <svg className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Licensed Visa Sponsor
                  </div>
                )}
              </div>
              <Link
                href={`/companies/${job.company.slug}`}
                className="block w-full mt-4 px-4 py-2 border border-blue-600 text-blue-600 font-medium rounded-md hover:bg-blue-50 text-center transition-colors"
              >
                View Company Profile
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}