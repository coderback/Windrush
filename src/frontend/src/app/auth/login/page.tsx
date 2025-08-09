import LoginForm from '@/components/auth/LoginForm';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Sign In | Windrush',
  description: 'Sign in to your Windrush account to access job applications and saved jobs.',
};

export default function LoginPage() {
  return <LoginForm />;
}