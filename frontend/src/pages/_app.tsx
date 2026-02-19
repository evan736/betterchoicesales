import type { AppProps } from 'next/app';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import { ThemeProvider } from '../contexts/ThemeContext';
import '../styles/globals.css';
import '../styles/mission-control.css';
import '../styles/sakura-pink.css';
import '../styles/apple-clean.css';
import '../styles/blue-white.css';

function InnerApp({ Component, pageProps }: { Component: any; pageProps: any }) {
  const { user } = useAuth();
  return (
    <ThemeProvider userId={user?.id}>
      <Component {...pageProps} />
    </ThemeProvider>
  );
}

export default function App({ Component, pageProps }: AppProps) {
  return (
    <AuthProvider>
      <InnerApp Component={Component} pageProps={pageProps} />
    </AuthProvider>
  );
}
