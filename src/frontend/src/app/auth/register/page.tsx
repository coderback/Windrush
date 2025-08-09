import RegisterForm from '@/components/auth/RegisterForm';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Create Account | Windrush',
  description: 'Create your Windrush account to apply for UK jobs with visa sponsorship.',
};

export default function RegisterPage() {
  return <RegisterForm />;
}