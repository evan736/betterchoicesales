import React, { createContext, useContext, useState, useCallback } from 'react';

interface ChatContextType {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  openSidebar: () => void;
  closeSidebar: () => void;
}

const ChatContext = createContext<ChatContextType>({
  sidebarOpen: false,
  toggleSidebar: () => {},
  openSidebar: () => {},
  closeSidebar: () => {},
});

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const toggleSidebar = useCallback(() => setSidebarOpen(prev => !prev), []);
  const openSidebar = useCallback(() => setSidebarOpen(true), []);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  return (
    <ChatContext.Provider value={{ sidebarOpen, toggleSidebar, openSidebar, closeSidebar }}>
      {children}
    </ChatContext.Provider>
  );
}

export function useChat() {
  return useContext(ChatContext);
}
