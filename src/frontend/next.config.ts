import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enable standalone output for Docker
  output: 'standalone',
  
  // API configuration
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: process.env.NEXT_PUBLIC_API_URL || 'http://backend:8000/api/:path*',
      },
    ];
  },
  
  // Image optimization
  images: {
    domains: ['localhost', '127.0.0.1', 'windrush-files.s3.amazonaws.com'],
  },
  
  // Environment variables
  env: {
    CUSTOM_KEY: 'windrush',
  },
};

export default nextConfig;
