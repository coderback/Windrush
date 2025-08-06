#!/usr/bin/env python3
"""
Windrush API Test Script

This script tests the basic functionality of the Windrush API.
Run this after starting the development server to verify everything is working.

Usage:
    python test_api.py

Requirements:
    pip install requests
"""

import requests
import json
import sys
from time import sleep

# Configuration
BASE_URL = "http://localhost:8000"
API_BASE = f"{BASE_URL}/api"

# Test data
TEST_USER_DATA = {
    "email": "test@example.com",
    "username": "testuser",
    "first_name": "Test",
    "last_name": "User",
    "password": "testpass123",
    "password_confirm": "testpass123",
    "user_type": "job_seeker"
}

class APITester:
    def __init__(self):
        self.session = requests.Session()
        self.token = None
        self.user_id = None
        
    def log(self, message, status="INFO"):
        print(f"[{status}] {message}")
        
    def test_health_check(self):
        """Test API health endpoint"""
        self.log("Testing health check...")
        
        try:
            response = self.session.get(f"{API_BASE}/health/")
            response.raise_for_status()
            
            data = response.json()
            assert data['status'] == 'healthy'
            
            self.log("✅ Health check passed")
            return True
            
        except Exception as e:
            self.log(f"❌ Health check failed: {e}", "ERROR")
            return False
    
    def test_api_root(self):
        """Test API root endpoint"""
        self.log("Testing API root...")
        
        try:
            response = self.session.get(f"{API_BASE}/")
            response.raise_for_status()
            
            data = response.json()
            assert 'endpoints' in data
            
            self.log("✅ API root accessible")
            return True
            
        except Exception as e:
            self.log(f"❌ API root failed: {e}", "ERROR")
            return False
    
    def test_user_registration(self):
        """Test user registration"""
        self.log("Testing user registration...")
        
        try:
            response = self.session.post(
                f"{API_BASE}/auth/register/",
                json=TEST_USER_DATA,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 400:
                # User might already exist, try to login instead
                self.log("User might already exist, will try login...")
                return True
                
            response.raise_for_status()
            
            data = response.json()
            assert 'token' in data
            assert 'user' in data
            
            self.token = data['token']
            self.user_id = data['user']['id']
            
            self.log("✅ User registration successful")
            return True
            
        except Exception as e:
            self.log(f"❌ User registration failed: {e}", "ERROR")
            if hasattr(e, 'response') and e.response is not None:
                self.log(f"Response: {e.response.text}", "ERROR")
            return False
    
    def test_user_login(self):
        """Test user login"""
        self.log("Testing user login...")
        
        try:
            login_data = {
                "email": TEST_USER_DATA["email"],
                "password": TEST_USER_DATA["password"]
            }
            
            response = self.session.post(
                f"{API_BASE}/auth/login/",
                json=login_data,
                headers={'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            
            data = response.json()
            assert 'token' in data
            assert 'user' in data
            
            self.token = data['token']
            self.user_id = data['user']['id']
            
            self.log("✅ User login successful")
            return True
            
        except Exception as e:
            self.log(f"❌ User login failed: {e}", "ERROR")
            if hasattr(e, 'response') and e.response is not None:
                self.log(f"Response: {e.response.text}", "ERROR")
            return False
    
    def test_authenticated_request(self):
        """Test authenticated request"""
        self.log("Testing authenticated request...")
        
        if not self.token:
            self.log("❌ No token available for authenticated request", "ERROR")
            return False
        
        try:
            headers = {
                'Authorization': f'Token {self.token}',
                'Content-Type': 'application/json'
            }
            
            response = self.session.get(
                f"{API_BASE}/auth/profile/",
                headers=headers
            )
            response.raise_for_status()
            
            data = response.json()
            assert 'email' in data
            assert data['email'] == TEST_USER_DATA['email']
            
            self.log("✅ Authenticated request successful")
            return True
            
        except Exception as e:
            self.log(f"❌ Authenticated request failed: {e}", "ERROR")
            if hasattr(e, 'response') and e.response is not None:
                self.log(f"Response: {e.response.text}", "ERROR")
            return False
    
    def test_user_stats(self):
        """Test user stats endpoint"""
        self.log("Testing user stats...")
        
        if not self.token:
            self.log("❌ No token available for stats request", "ERROR")
            return False
        
        try:
            headers = {
                'Authorization': f'Token {self.token}',
                'Content-Type': 'application/json'
            }
            
            response = self.session.get(
                f"{API_BASE}/auth/stats/",
                headers=headers
            )
            response.raise_for_status()
            
            data = response.json()
            assert isinstance(data, dict)
            
            self.log("✅ User stats request successful")
            return True
            
        except Exception as e:
            self.log(f"❌ User stats failed: {e}", "ERROR")
            if hasattr(e, 'response') and e.response is not None:
                self.log(f"Response: {e.response.text}", "ERROR")
            return False
    
    def test_logout(self):
        """Test user logout"""
        self.log("Testing user logout...")
        
        if not self.token:
            self.log("❌ No token available for logout", "ERROR")
            return False
        
        try:
            headers = {
                'Authorization': f'Token {self.token}',
                'Content-Type': 'application/json'
            }
            
            response = self.session.post(
                f"{API_BASE}/auth/logout/",
                headers=headers
            )
            response.raise_for_status()
            
            self.token = None
            self.user_id = None
            
            self.log("✅ User logout successful")
            return True
            
        except Exception as e:
            self.log(f"❌ User logout failed: {e}", "ERROR")
            if hasattr(e, 'response') and e.response is not None:
                self.log(f"Response: {e.response.text}", "ERROR")
            return False
    
    def run_all_tests(self):
        """Run all API tests"""
        self.log("🚀 Starting Windrush API Tests", "INFO")
        self.log("-" * 50)
        
        tests = [
            ("Health Check", self.test_health_check),
            ("API Root", self.test_api_root),
            ("User Registration", self.test_user_registration),
            ("User Login", self.test_user_login),
            ("Authenticated Request", self.test_authenticated_request),
            ("User Stats", self.test_user_stats),
            ("User Logout", self.test_logout),
        ]
        
        passed = 0
        failed = 0
        
        for test_name, test_func in tests:
            self.log(f"\n--- {test_name} ---")
            
            try:
                if test_func():
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                self.log(f"❌ {test_name} crashed: {e}", "ERROR")
                failed += 1
            
            sleep(0.5)  # Brief pause between tests
        
        self.log("\n" + "=" * 50)
        self.log(f"📊 Test Results: {passed} passed, {failed} failed")
        
        if failed == 0:
            self.log("🎉 All tests passed! API is working correctly.", "SUCCESS")
            return True
        else:
            self.log(f"⚠️  {failed} tests failed. Check the logs above.", "WARNING")
            return False

def main():
    """Main function"""
    print("Windrush API Test Suite")
    print("=" * 50)
    
    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/api/health/", timeout=5)
        if response.status_code != 200:
            print("❌ Server is not responding properly")
            print("Make sure the Django development server is running on localhost:8000")
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to server")
        print("Make sure the Django development server is running:")
        print("  python manage.py runserver")
        print("Or using Docker:")
        print("  make up")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("❌ Server response timeout")
        sys.exit(1)
    
    # Run tests
    tester = APITester()
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()