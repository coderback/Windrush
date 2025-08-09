import { 
  User, 
  Company, 
  Job, 
  Application, 
  LoginCredentials, 
  RegisterData, 
  AuthResponse,
  JobSearchParams,
  CompanySearchParams,
  PaginatedResponse,
  ApiError
} from '@/types/api';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const API_URL = `${API_BASE_URL}/api`;

// API Client Class
class ApiClient {
  private baseURL: string;
  private token: string | null = null;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
    
    // Load token from localStorage on client side
    if (typeof window !== 'undefined') {
      this.token = localStorage.getItem('auth_token');
    }
  }

  // Set authentication token
  setToken(token: string | null) {
    this.token = token;
    if (typeof window !== 'undefined') {
      if (token) {
        localStorage.setItem('auth_token', token);
      } else {
        localStorage.removeItem('auth_token');
      }
    }
  }

  // Get authentication headers
  private getHeaders(contentType: string = 'application/json'): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': contentType,
    };

    if (this.token) {
      headers.Authorization = `Token ${this.token}`;
    }

    return headers;
  }

  // Generic request method
  private async request<T>(
    endpoint: string, 
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;
    
    const config: RequestInit = {
      ...options,
      headers: {
        ...this.getHeaders(),
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, config);
      const data = await response.json();

      if (!response.ok) {
        throw {
          status: response.status,
          ...data
        } as ApiError & { status: number };
      }

      return data;
    } catch (error) {
      if (error instanceof Error) {
        throw new Error(`Network error: ${error.message}`);
      }
      throw error;
    }
  }

  // Authentication Methods
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const response = await this.request<AuthResponse>('/auth/login/', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
    
    this.setToken(response.token);
    return response;
  }

  async register(data: RegisterData): Promise<AuthResponse> {
    const response = await this.request<AuthResponse>('/auth/register/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    
    this.setToken(response.token);
    return response;
  }

  async logout(): Promise<void> {
    try {
      await this.request('/auth/logout/', {
        method: 'POST',
      });
    } finally {
      this.setToken(null);
    }
  }

  async getCurrentUser(): Promise<User> {
    return this.request<User>('/auth/user/');
  }

  async updateProfile(data: Partial<User>): Promise<User> {
    return this.request<User>('/auth/user/', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  // Job Methods
  async getJobs(params: JobSearchParams = {}): Promise<PaginatedResponse<Job>> {
    const searchParams = new URLSearchParams();
    
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        if (Array.isArray(value)) {
          value.forEach(item => searchParams.append(key, item.toString()));
        } else {
          searchParams.append(key, value.toString());
        }
      }
    });

    const queryString = searchParams.toString();
    return this.request<PaginatedResponse<Job>>(
      `/jobs/${queryString ? `?${queryString}` : ''}`
    );
  }

  async getJob(slug: string): Promise<Job> {
    return this.request<Job>(`/jobs/${slug}/`);
  }

  async getFeaturedJobs(): Promise<Job[]> {
    return this.request<Job[]>('/jobs/featured/');
  }

  async searchJobs(params: JobSearchParams): Promise<PaginatedResponse<Job>> {
    const searchParams = new URLSearchParams();
    
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        if (Array.isArray(value)) {
          value.forEach(item => searchParams.append(key, item.toString()));
        } else {
          searchParams.append(key, value.toString());
        }
      }
    });

    return this.request<PaginatedResponse<Job>>(
      `/jobs/search/?${searchParams.toString()}`
    );
  }

  // Company Methods
  async getCompanies(params: CompanySearchParams = {}): Promise<PaginatedResponse<Company>> {
    const searchParams = new URLSearchParams();
    
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        if (Array.isArray(value)) {
          value.forEach(item => searchParams.append(key, item.toString()));
        } else {
          searchParams.append(key, value.toString());
        }
      }
    });

    const queryString = searchParams.toString();
    return this.request<PaginatedResponse<Company>>(
      `/companies/${queryString ? `?${queryString}` : ''}`
    );
  }

  async getCompany(slug: string): Promise<Company> {
    return this.request<Company>(`/companies/${slug}/`);
  }

  async getFeaturedCompanies(): Promise<Company[]> {
    return this.request<Company[]>('/companies/featured/');
  }

  async searchCompanies(params: CompanySearchParams): Promise<PaginatedResponse<Company>> {
    const searchParams = new URLSearchParams();
    
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        if (Array.isArray(value)) {
          value.forEach(item => searchParams.append(key, item.toString()));
        } else {
          searchParams.append(key, value.toString());
        }
      }
    });

    return this.request<PaginatedResponse<Company>>(
      `/companies/search/?${searchParams.toString()}`
    );
  }

  // Application Methods
  async getApplications(): Promise<PaginatedResponse<Application>> {
    return this.request<PaginatedResponse<Application>>('/applications/');
  }

  async getApplication(id: number): Promise<Application> {
    return this.request<Application>(`/applications/${id}/`);
  }

  async applyToJob(jobId: number, applicationData: {
    cover_letter: string;
    expected_salary?: number;
    available_start_date?: string;
    requires_sponsorship: boolean;
  }): Promise<Application> {
    return this.request<Application>('/applications/', {
      method: 'POST',
      body: JSON.stringify({
        job: jobId,
        ...applicationData,
      }),
    });
  }

  async withdrawApplication(id: number): Promise<void> {
    await this.request(`/applications/${id}/withdraw/`, {
      method: 'POST',
    });
  }

  // Utility method to check if user is authenticated
  isAuthenticated(): boolean {
    return !!this.token;
  }
}

// Create and export API client instance
export const apiClient = new ApiClient(API_URL);

// Export utility functions
export const isAuthenticated = () => apiClient.isAuthenticated();
export const setAuthToken = (token: string | null) => apiClient.setToken(token);