import type { AppProps } from 'next/app';
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

function AppLayout({ Component, pageProps }: { Component: any; pageProps: any }) {
  const { user } = useAuth();
  const { sidebarOpen: chatOpen } = useChat();
  const { sidebarOpen: emailOpen } = useEmail();

  if (!user) {
    return <Component {...pageProps} />;
  }

  // Calculate right margin: shared sidebar bar (48px) or expanded panel (380px)
  // Only one panel can be expanded at a time — they share the same space
  const rightMargin = chatOpen || emailOpen ? 380 : 48;

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
    <AuthProvider>
      <InnerApp Component={Component} pageProps={pageProps} />
    </AuthProvider>
  );
}
