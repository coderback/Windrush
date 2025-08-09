'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { apiClient } from '@/lib/api';
import { Job, JobSearchParams, PaginatedResponse } from '@/types/api';

interface SearchFilters extends JobSearchParams {
  search?: string;
  location?: string;
  job_type?: string;
  experience_level?: string;
  salary_min?: number;
  visa_sponsorship?: boolean;
  is_featured?: boolean;
  posted_within?: 'today' | 'week' | 'month';
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasNextPage, setHasNextPage] = useState(false);
  const [hasPreviousPage, setHasPreviousPage] = useState(false);

  const [filters, setFilters] = useState<SearchFilters>({
    search: '',
    location: '',
    visa_sponsorship: true, // Default to showing only sponsored jobs
    ordering: '-created_at'
  });

  const [searchInput, setSearchInput] = useState('');
  const [locationInput, setLocationInput] = useState('');

  // Job type options
  const jobTypeOptions = [
    { value: '', label: 'All Job Types' },
    { value: 'full_time', label: 'Full Time' },
    { value: 'part_time', label: 'Part Time' },
    { value: 'contract', label: 'Contract' },
    { value: 'internship', label: 'Internship' },
    { value: 'placement', label: 'Placement Year' },
    { value: 'graduate_scheme', label: 'Graduate Scheme' },
  ];

  const experienceLevelOptions = [
    { value: '', label: 'All Experience Levels' },
    { value: 'entry', label: 'Entry Level (0-2 years)' },
    { value: 'junior', label: 'Junior (1-3 years)' },
    { value: 'mid', label: 'Mid Level (3-5 years)' },
    { value: 'senior', label: 'Senior (5+ years)' },
    { value: 'lead', label: 'Lead/Principal (7+ years)' },
  ];

  const postedWithinOptions = [
    { value: '', label: 'All Time' },
    { value: 'today', label: 'Today' },
    { value: 'week', label: 'This Week' },
    { value: 'month', label: 'This Month' },
  ];

  const fetchJobs = async (page: number = 1) => {
    try {
      setLoading(true);
      const searchParams = {
        ...filters,
        page: page
      };
      
      const response: PaginatedResponse<Job> = await apiClient.getJobs(searchParams);
      
      setJobs(response.results);
      setTotalCount(response.count);
      setHasNextPage(!!response.next);
      setHasPreviousPage(!!response.previous);
      setCurrentPage(page);
      setError(null);
    } catch (err) {
      setError('Failed to fetch jobs. Please try again.');
      console.error('Error fetching jobs:', err);
    } finally {
      setLoading(false);
    }
  };

  // Load jobs when component mounts or filters change
  useEffect(() => {
    fetchJobs();
  }, [filters]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setFilters(prev => ({
      ...prev,
      search: searchInput,
      location: locationInput,
    }));
  };

  const handleFilterChange = (key: keyof SearchFilters, value: any) => {
    setFilters(prev => ({
      ...prev,
      [key]: value,
    }));
  };

  const clearFilters = () => {
    setFilters({
      search: '',
      location: '',
      visa_sponsorship: true,
      ordering: '-created_at'
    });
    setSearchInput('');
    setLocationInput('');
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

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">Find Jobs</h1>
              <p className="mt-1 text-gray-600">
                {totalCount} jobs with visa sponsorship available
              </p>
            </div>
            <Link
              href="/"
              className="text-blue-600 hover:text-blue-800 font-medium"
            >
              ← Back to Home
            </Link>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
          {/* Filters Sidebar */}
          <div className="lg:col-span-1">
            <div className="bg-white rounded-lg shadow-sm p-6">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-lg font-semibold text-gray-900">Filters</h2>
                <button
                  onClick={clearFilters}
                  className="text-sm text-blue-600 hover:text-blue-800"
                >
                  Clear all
                </button>
              </div>

              {/* Search Form */}
              <form onSubmit={handleSearch} className="space-y-4 mb-6">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Job Title or Keywords
                  </label>
                  <input
                    type="text"
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    placeholder="e.g. Software Engineer, Data Analyst"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Location
                  </label>
                  <input
                    type="text"
                    value={locationInput}
                    onChange={(e) => setLocationInput(e.target.value)}
                    placeholder="e.g. London, Manchester"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <button
                  type="submit"
                  className="w-full px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 font-medium"
                >
                  Search Jobs
                </button>
              </form>

              {/* Filter Options */}
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Job Type
                  </label>
                  <select
                    value={filters.job_type || ''}
                    onChange={(e) => handleFilterChange('job_type', e.target.value || undefined)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {jobTypeOptions.map(option => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Experience Level
                  </label>
                  <select
                    value={filters.experience_level || ''}
                    onChange={(e) => handleFilterChange('experience_level', e.target.value || undefined)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {experienceLevelOptions.map(option => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Posted Within
                  </label>
                  <select
                    value={filters.posted_within || ''}
                    onChange={(e) => handleFilterChange('posted_within', e.target.value as 'today' | 'week' | 'month' || undefined)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {postedWithinOptions.map(option => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Minimum Salary (£)
                  </label>
                  <input
                    type="number"
                    value={filters.salary_min || ''}
                    onChange={(e) => handleFilterChange('salary_min', e.target.value ? parseInt(e.target.value) : undefined)}
                    placeholder="e.g. 25000"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div className="flex items-center">
                  <input
                    type="checkbox"
                    id="visa_sponsorship"
                    checked={filters.visa_sponsorship || false}
                    onChange={(e) => handleFilterChange('visa_sponsorship', e.target.checked)}
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                  />
                  <label htmlFor="visa_sponsorship" className="ml-2 text-sm text-gray-700">
                    Visa sponsorship available
                  </label>
                </div>

                <div className="flex items-center">
                  <input
                    type="checkbox"
                    id="is_featured"
                    checked={filters.is_featured || false}
                    onChange={(e) => handleFilterChange('is_featured', e.target.checked)}
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                  />
                  <label htmlFor="is_featured" className="ml-2 text-sm text-gray-700">
                    Featured jobs only
                  </label>
                </div>
              </div>
            </div>
          </div>

          {/* Job Listings */}
          <div className="lg:col-span-3">
            {/* Sort Options */}
            <div className="bg-white rounded-lg shadow-sm p-4 mb-6">
              <div className="flex justify-between items-center">
                <div className="text-sm text-gray-600">
                  Showing {jobs.length} of {totalCount} jobs
                </div>
                <div className="flex items-center space-x-2">
                  <label className="text-sm text-gray-700">Sort by:</label>
                  <select
                    value={filters.ordering || '-created_at'}
                    onChange={(e) => handleFilterChange('ordering', e.target.value)}
                    className="px-3 py-1 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="-created_at">Newest First</option>
                    <option value="created_at">Oldest First</option>
                    <option value="title">Job Title A-Z</option>
                    <option value="-title">Job Title Z-A</option>
                    <option value="-salary_min">Highest Salary</option>
                    <option value="salary_min">Lowest Salary</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Loading State */}
            {loading && (
              <div className="flex justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
              </div>
            )}

            {/* Error State */}
            {error && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
                <p className="text-red-700">{error}</p>
              </div>
            )}

            {/* Job Cards */}
            {!loading && !error && (
              <div className="space-y-4">
                {jobs.length === 0 ? (
                  <div className="bg-white rounded-lg shadow-sm p-8 text-center">
                    <div className="text-gray-400 mb-4">
                      <svg className="mx-auto h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                      </svg>
                    </div>
                    <h3 className="text-lg font-medium text-gray-900 mb-2">No jobs found</h3>
                    <p className="text-gray-600 mb-4">
                      Try adjusting your search criteria or clearing some filters.
                    </p>
                    <button
                      onClick={clearFilters}
                      className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
                    >
                      Clear Filters
                    </button>
                  </div>
                ) : (
                  jobs.map((job) => (
                    <div key={job.id} className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 hover:shadow-md transition-shadow">
                      <div className="flex justify-between items-start mb-4">
                        <div className="flex-1">
                          <div className="flex items-center space-x-2 mb-2">
                            <Link
                              href={`/jobs/${job.slug}`}
                              className="text-xl font-semibold text-gray-900 hover:text-blue-600"
                            >
                              {job.title}
                            </Link>
                            {job.is_featured && (
                              <span className="px-2 py-1 bg-yellow-100 text-yellow-800 text-xs font-medium rounded-full">
                                Featured
                              </span>
                            )}
                            {job.is_urgent && (
                              <span className="px-2 py-1 bg-red-100 text-red-800 text-xs font-medium rounded-full">
                                Urgent
                              </span>
                            )}
                          </div>
                          <Link
                            href={`/companies/${job.company.slug}`}
                            className="text-lg text-blue-600 hover:text-blue-800 font-medium"
                          >
                            {job.company.name}
                          </Link>
                        </div>
                        <div className="text-right">
                          <div className="text-lg font-semibold text-gray-900">
                            {formatSalary(job)}
                          </div>
                          <div className="text-sm text-gray-500">
                            per year
                          </div>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-4 mb-4 text-sm text-gray-600">
                        <div className="flex items-center">
                          <svg className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                          </svg>
                          {job.location}
                        </div>
                        <div className="flex items-center">
                          <svg className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m8 0V6a2 2 0 00-2 2H8a2 2 0 00-2-2V6m8 0h2a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h2" />
                          </svg>
                          {formatJobType(job.job_type)}
                        </div>
                        <div className="flex items-center">
                          <svg className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                          {job.days_since_posted === 0 ? 'Today' : 
                           job.days_since_posted === 1 ? '1 day ago' :
                           `${job.days_since_posted} days ago`}
                        </div>
                        {job.visa_sponsorship_available && (
                          <div className="flex items-center text-green-600">
                            <svg className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            Visa Sponsorship
                          </div>
                        )}
                      </div>

                      <div className="mb-4">
                        <p className="text-gray-700 line-clamp-2">
                          {job.description.replace(/<[^>]*>/g, '').substring(0, 200)}...
                        </p>
                      </div>

                      <div className="flex justify-between items-center">
                        <div className="flex flex-wrap gap-2">
                          {job.skills_required.slice(0, 3).map((skill, index) => (
                            <span
                              key={index}
                              className="px-2 py-1 bg-blue-100 text-blue-800 text-xs font-medium rounded-full"
                            >
                              {skill}
                            </span>
                          ))}
                          {job.skills_required.length > 3 && (
                            <span className="px-2 py-1 bg-gray-100 text-gray-800 text-xs font-medium rounded-full">
                              +{job.skills_required.length - 3} more
                            </span>
                          )}
                        </div>
                        <Link
                          href={`/jobs/${job.slug}`}
                          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 font-medium transition-colors"
                        >
                          View Details
                        </Link>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Pagination */}
            {!loading && jobs.length > 0 && (totalCount > 20) && (
              <div className="bg-white rounded-lg shadow-sm p-4 mt-6">
                <div className="flex justify-between items-center">
                  <button
                    onClick={() => fetchJobs(currentPage - 1)}
                    disabled={!hasPreviousPage}
                    className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Previous
                  </button>
                  <div className="text-sm text-gray-700">
                    Page {currentPage} of {Math.ceil(totalCount / 20)}
                  </div>
                  <button
                    onClick={() => fetchJobs(currentPage + 1)}
                    disabled={!hasNextPage}
                    className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}