import type { AppProps } from 'next/app';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import { ThemeProvider } from '../contexts/ThemeContext';
import { ChatProvider, useChat } from '../contexts/ChatContext';
import dynamic from 'next/dynamic';
import '../styles/globals.css';
import '../styles/mission-control.css';
import '../styles/sakura-pink.css';
import '../styles/apple-clean.css';
import '../styles/blue-white.css';
import '../styles/true-black.css';

const ChatSidebar = dynamic(() => import('../components/ChatPanel'), { ssr: false });

function AppLayout({ Component, pageProps }: { Component: any; pageProps: any }) {
  const { user } = useAuth();
  const { sidebarOpen } = useChat();

  if (!user) {
    return <Component {...pageProps} />;
  }

  return (
    <div className="flex min-h-screen">
      {/* Main content — shrinks when sidebar open */}
      <div
        className="flex-1 min-w-0 transition-all duration-300"
        style={{ marginRight: sidebarOpen ? '380px' : '48px' }}
      >
        <Component {...pageProps} />
      </div>

      {/* Chat sidebar — fixed right */}
      <ChatSidebar />
    </div>
  );
}

function InnerApp({ Component, pageProps }: { Component: any; pageProps: any }) {
  const { user } = useAuth();
  return (
    <ThemeProvider userId={user?.id}>
      <ChatProvider>
        <AppLayout Component={Component} pageProps={pageProps} />
      </ChatProvider>
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
