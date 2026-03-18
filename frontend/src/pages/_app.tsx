import type { AppProps } from 'next/app';
import React from 'react';
import Script from 'next/script';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import { ThemeProvider } from '../contexts/ThemeContext';
import { ChatProvider, useChat } from '../contexts/ChatContext';
import { EmailProvider, useEmail } from '../contexts/EmailContext';
import dynamic from 'next/dynamic';
import '../styles/globals.css';
import '../styles/mission-control.css';
import '../styles/sakura-pink.css';
import '../styles/apple-clean.css';
import '../styles/blue-white.css';
import '../styles/true-black.css';

const ChatSidebar = dynamic(() => import('../components/ChatPanel'), { ssr: false });
const EmailSidebar = dynamic(() => import('../components/EmailPanel'), { ssr: false });
const TicketReporter = dynamic(() => import('../components/TicketReporter'), { ssr: false });

// ── Error Boundary — catches React crashes and shows recovery UI ──
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ORBIT Error Boundary caught:', error, errorInfo);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: '#0a1628', color: '#e2e8f0', fontFamily: 'Arial, sans-serif',
        }}>
          <div style={{ textAlign: 'center', maxWidth: '480px', padding: '40px' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>⚠️</div>
            <h1 style={{ fontSize: '24px', fontWeight: 700, marginBottom: '8px', color: '#fff' }}>
              Something went wrong
            </h1>
            <p style={{ color: '#94a3b8', marginBottom: '24px', fontSize: '14px' }}>
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
              <button
                onClick={() => { this.setState({ hasError: false, error: null }); }}
                style={{
                  padding: '10px 20px', borderRadius: '8px', border: '1px solid rgba(6,182,212,0.3)',
                  background: 'rgba(6,182,212,0.1)', color: '#22d3ee', fontWeight: 600,
                  cursor: 'pointer', fontSize: '14px',
                }}
              >
                Try Again
              </button>
              <button
                onClick={() => { window.location.href = '/dashboard'; }}
                style={{
                  padding: '10px 20px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)',
                  background: 'rgba(255,255,255,0.05)', color: '#94a3b8', fontWeight: 600,
                  cursor: 'pointer', fontSize: '14px',
                }}
              >
                Go to Dashboard
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function AppLayout({ Component, pageProps }: { Component: any; pageProps: any }) {
  const { user } = useAuth();
  const { sidebarOpen: chatOpen } = useChat();
  const { sidebarOpen: emailOpen, expanded: emailExpanded } = useEmail();

  if (!user) {
    return <Component {...pageProps} />;
  }

  // Calculate right margin: collapsed bar (48px) + any open panels
  const chatWidth = chatOpen ? 380 : 0;
  const emailWidth = emailOpen ? (emailExpanded ? 680 : 380) : 0;
  const barWidth = 48; // always-visible icon bar
  const rightMargin = barWidth + chatWidth + emailWidth;

  return (
    <div className="flex min-h-screen">
      {/* Main content — shrinks when sidebars open */}
      <div
        className="flex-1 min-w-0 transition-all duration-300"
        style={{ marginRight: `${rightMargin}px` }}
      >
        <Component {...pageProps} />
      </div>

      {/* Email sidebar — positioned to the left of chat */}
      <EmailSidebar />
      {/* Chat sidebar — fixed right edge */}
      <ChatSidebar />
      {/* Ticket reporter — floating button on every page */}
      <TicketReporter />
    </div>
  );
}

function InnerApp({ Component, pageProps }: { Component: any; pageProps: any }) {
  const { user } = useAuth();
  return (
    <ThemeProvider userId={user?.id}>
      <ChatProvider>
        <EmailProvider>
          <AppLayout Component={Component} pageProps={pageProps} />
        </EmailProvider>
      </ChatProvider>
    </ThemeProvider>
  );
}

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      {/* Google Analytics */}
      <Script
        src="https://www.googletagmanager.com/gtag/js?id=G-L5NSC0W4E0"
        strategy="afterInteractive"
      />
      <Script id="gtag-init" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          gtag('config', 'G-L5NSC0W4E0');
        `}
      </Script>
      <ErrorBoundary>
        <AuthProvider>
          <InnerApp Component={Component} pageProps={pageProps} />
        </AuthProvider>
      </ErrorBoundary>
    </>
  );
}
