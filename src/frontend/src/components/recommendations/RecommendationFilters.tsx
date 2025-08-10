'use client';

interface RecommendationFiltersProps {
  onFilterChange: (filters: {
    sortBy?: 'match_score' | 'created_at' | 'salary';
    showViewed?: boolean;
    showClicked?: boolean;
    minMatchScore?: number;
  }) => void;
}

export default function RecommendationFilters({ onFilterChange }: RecommendationFiltersProps) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 mb-6">
      <div className="flex flex-wrap gap-4 items-center">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Sort by
          </label>
          <select
            onChange={(e) => onFilterChange({ sortBy: e.target.value as any })}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          >
            <option value="match_score">Match Score</option>
            <option value="created_at">Most Recent</option>
            <option value="salary">Salary</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Min Match Score
          </label>
          <select
            onChange={(e) => onFilterChange({ minMatchScore: parseInt(e.target.value) })}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          >
            <option value="0">Any Match</option>
            <option value="50">50%+ Match</option>
            <option value="70">70%+ Match</option>
            <option value="80">80%+ Match</option>
          </select>
        </div>

        <div className="flex items-center space-x-4">
          <label className="flex items-center">
            <input
              type="checkbox"
              onChange={(e) => onFilterChange({ showViewed: e.target.checked })}
              className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
            />
            <span className="ml-2 text-sm text-gray-700">Show viewed</span>
          </label>

          <label className="flex items-center">
            <input
              type="checkbox"
              onChange={(e) => onFilterChange({ showClicked: e.target.checked })}
              className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
            />
            <span className="ml-2 text-sm text-gray-700">Show clicked</span>
          </label>
        </div>
      </div>
    </div>
  );
}