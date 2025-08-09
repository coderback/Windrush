'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { apiClient } from '@/lib/api';
import { Company, CompanySearchParams, PaginatedResponse } from '@/types/api';

interface SearchFilters extends CompanySearchParams {
  search?: string;
  industry?: string;
  location?: string;
  company_size?: string;
  sponsor_status?: string;
  has_active_jobs?: boolean;
  is_featured?: boolean;
}

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasNextPage, setHasNextPage] = useState(false);
  const [hasPreviousPage, setHasPreviousPage] = useState(false);

  const [filters, setFilters] = useState<SearchFilters>({
    search: '',
    location: '',
    sponsor_status: 'active', // Default to active sponsors only
    has_active_jobs: true,
    ordering: 'name'
  });

  const [searchInput, setSearchInput] = useState('');
  const [locationInput, setLocationInput] = useState('');

  // Filter options
  const companySizeOptions = [
    { value: '', label: 'All Company Sizes' },
    { value: 'startup', label: 'Startup (1-10 employees)' },
    { value: 'small', label: 'Small (11-50 employees)' },
    { value: 'medium', label: 'Medium (51-250 employees)' },
    { value: 'large', label: 'Large (251-1000 employees)' },
    { value: 'enterprise', label: 'Enterprise (1000+ employees)' },
  ];

  const sponsorStatusOptions = [
    { value: '', label: 'All Companies' },
    { value: 'active', label: 'Active Sponsors Only' },
    { value: 'inactive', label: 'Inactive Sponsors' },
    { value: 'pending', label: 'Pending Verification' },
  ];

  const industryOptions = [
    { value: '', label: 'All Industries' },
    { value: 'Technology', label: 'Technology' },
    { value: 'Finance', label: 'Finance & Banking' },
    { value: 'Healthcare', label: 'Healthcare & Life Sciences' },
    { value: 'Engineering', label: 'Engineering & Manufacturing' },
    { value: 'Consulting', label: 'Consulting' },
    { value: 'Media', label: 'Media & Marketing' },
    { value: 'Retail', label: 'Retail & E-commerce' },
    { value: 'Education', label: 'Education' },
    { value: 'Legal', label: 'Legal Services' },
    { value: 'Other', label: 'Other' },
  ];

  const fetchCompanies = async (page: number = 1) => {
    try {
      setLoading(true);
      const searchParams = {
        ...filters,
        page: page
      };
      
      const response: PaginatedResponse<Company> = await apiClient.getCompanies(searchParams);
      
      setCompanies(response.results);
      setTotalCount(response.count);
      setHasNextPage(!!response.next);
      setHasPreviousPage(!!response.previous);
      setCurrentPage(page);
      setError(null);
    } catch (err) {
      setError('Failed to fetch companies. Please try again.');
      console.error('Error fetching companies:', err);
    } finally {
      setLoading(false);
    }
  };

  // Load companies when component mounts or filters change
  useEffect(() => {
    fetchCompanies();
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
      sponsor_status: 'active',
      has_active_jobs: true,
      ordering: 'name'
    });
    setSearchInput('');
    setLocationInput('');
  };

  const formatCompanySize = (size: string) => {
    const sizeLabels: { [key: string]: string } = {
      'startup': '1-10 employees',
      'small': '11-50 employees',
      'medium': '51-250 employees',
      'large': '251-1000 employees',
      'enterprise': '1000+ employees'
    };
    return sizeLabels[size] || size;
  };

  const getSponsorBadgeColor = (status: string) => {
    switch (status) {
      case 'active': return 'bg-green-100 text-green-800';
      case 'inactive': return 'bg-red-100 text-red-800';
      case 'pending': return 'bg-yellow-100 text-yellow-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">Sponsor Companies</h1>
              <p className="mt-1 text-gray-600">
                {totalCount} companies that can sponsor UK work visas
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
                    Company Name
                  </label>
                  <input
                    type="text"
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    placeholder="e.g. Google, Microsoft"
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
                  Search Companies
                </button>
              </form>

              {/* Filter Options */}
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Industry
                  </label>
                  <select
                    value={filters.industry || ''}
                    onChange={(e) => handleFilterChange('industry', e.target.value || undefined)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {industryOptions.map(option => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Company Size
                  </label>
                  <select
                    value={filters.company_size || ''}
                    onChange={(e) => handleFilterChange('company_size', e.target.value || undefined)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {companySizeOptions.map(option => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Sponsor Status
                  </label>
                  <select
                    value={filters.sponsor_status || ''}
                    onChange={(e) => handleFilterChange('sponsor_status', e.target.value || undefined)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {sponsorStatusOptions.map(option => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center">
                  <input
                    type="checkbox"
                    id="has_active_jobs"
                    checked={filters.has_active_jobs || false}
                    onChange={(e) => handleFilterChange('has_active_jobs', e.target.checked)}
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                  />
                  <label htmlFor="has_active_jobs" className="ml-2 text-sm text-gray-700">
                    Has active job openings
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
                    Featured companies only
                  </label>
                </div>
              </div>
            </div>
          </div>

          {/* Company Listings */}
          <div className="lg:col-span-3">
            {/* Sort Options */}
            <div className="bg-white rounded-lg shadow-sm p-4 mb-6">
              <div className="flex justify-between items-center">
                <div className="text-sm text-gray-600">
                  Showing {companies.length} of {totalCount} companies
                </div>
                <div className="flex items-center space-x-2">
                  <label className="text-sm text-gray-700">Sort by:</label>
                  <select
                    value={filters.ordering || 'name'}
                    onChange={(e) => handleFilterChange('ordering', e.target.value)}
                    className="px-3 py-1 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="name">Company Name A-Z</option>
                    <option value="-name">Company Name Z-A</option>
                    <option value="-total_jobs_posted">Most Jobs Posted</option>
                    <option value="total_jobs_posted">Fewest Jobs Posted</option>
                    <option value="-created_at">Newest Companies</option>
                    <option value="created_at">Oldest Companies</option>
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

            {/* Company Cards */}
            {!loading && !error && (
              <div className="space-y-4">
                {companies.length === 0 ? (
                  <div className="bg-white rounded-lg shadow-sm p-8 text-center">
                    <div className="text-gray-400 mb-4">
                      <svg className="mx-auto h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-4m-5 0H9m0 0H5m-2 0h2m5 0v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5m6 0v-5a2 2 0 012-2h4a2 2 0 012 2v5" />
                      </svg>
                    </div>
                    <h3 className="text-lg font-medium text-gray-900 mb-2">No companies found</h3>
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
                  companies.map((company) => (
                    <div key={company.id} className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 hover:shadow-md transition-shadow">
                      <div className="flex justify-between items-start mb-4">
                        <div className="flex-1">
                          <div className="flex items-center space-x-2 mb-2">
                            <Link
                              href={`/companies/${company.slug}`}
                              className="text-xl font-semibold text-gray-900 hover:text-blue-600"
                            >
                              {company.name}
                            </Link>
                            {company.is_featured && (
                              <span className="px-2 py-1 bg-yellow-100 text-yellow-800 text-xs font-medium rounded-full">
                                Featured
                              </span>
                            )}
                            {company.is_premium_partner && (
                              <span className="px-2 py-1 bg-purple-100 text-purple-800 text-xs font-medium rounded-full">
                                Premium Partner
                              </span>
                            )}
                          </div>
                          <div className="text-gray-600 mb-1">{company.industry}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-lg font-semibold text-blue-600">
                            {company.active_jobs_count} Jobs
                          </div>
                          <div className="text-sm text-gray-500">
                            currently hiring
                          </div>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-4 mb-4 text-sm text-gray-600">
                        <div className="flex items-center">
                          <svg className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                          </svg>
                          {company.city}, {company.region}
                        </div>
                        <div className="flex items-center">
                          <svg className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                          </svg>
                          {formatCompanySize(company.company_size)}
                        </div>
                        {company.is_sponsor && (
                          <div className="flex items-center">
                            <span className={`px-2 py-1 text-xs font-medium rounded-full ${getSponsorBadgeColor(company.sponsor_status)}`}>
                              {company.sponsor_status.charAt(0).toUpperCase() + company.sponsor_status.slice(1)} Sponsor
                            </span>
                          </div>
                        )}
                        {company.can_sponsor_skilled_worker && (
                          <div className="flex items-center text-green-600">
                            <svg className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            Skilled Worker Visa
                          </div>
                        )}
                      </div>

                      <div className="flex justify-between items-center">
                        <div className="flex flex-wrap gap-2">
                          {company.sponsor_types.slice(0, 3).map((type, index) => (
                            <span
                              key={index}
                              className="px-2 py-1 bg-blue-100 text-blue-800 text-xs font-medium rounded-full capitalize"
                            >
                              {type.replace('_', ' ')}
                            </span>
                          ))}
                          {company.sponsor_types.length > 3 && (
                            <span className="px-2 py-1 bg-gray-100 text-gray-800 text-xs font-medium rounded-full">
                              +{company.sponsor_types.length - 3} more
                            </span>
                          )}
                        </div>
                        <div className="flex space-x-2">
                          {company.active_jobs_count > 0 && (
                            <Link
                              href={`/jobs?company=${encodeURIComponent(company.name)}`}
                              className="px-3 py-1 border border-blue-600 text-blue-600 text-sm font-medium rounded hover:bg-blue-50 transition-colors"
                            >
                              View Jobs
                            </Link>
                          )}
                          <Link
                            href={`/companies/${company.slug}`}
                            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-700 transition-colors"
                          >
                            View Profile
                          </Link>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Pagination */}
            {!loading && companies.length > 0 && (totalCount > 20) && (
              <div className="bg-white rounded-lg shadow-sm p-4 mt-6">
                <div className="flex justify-between items-center">
                  <button
                    onClick={() => fetchCompanies(currentPage - 1)}
                    disabled={!hasPreviousPage}
                    className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Previous
                  </button>
                  <div className="text-sm text-gray-700">
                    Page {currentPage} of {Math.ceil(totalCount / 20)}
                  </div>
                  <button
                    onClick={() => fetchCompanies(currentPage + 1)}
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