import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { emailAPI } from '../lib/api';

interface EmailContextType {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  openSidebar: () => void;
  closeSidebar: () => void;
  unreadCount: number;
  openCount: number;
  unassignedCount: number;
  refreshStats: () => void;
}

const EmailContext = createContext<EmailContextType>({
  sidebarOpen: false,
  toggleSidebar: () => {},
  openSidebar: () => {},
  closeSidebar: () => {},
  unreadCount: 0,
  openCount: 0,
  unassignedCount: 0,
  refreshStats: () => {},
});

export function EmailProvider({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [openCount, setOpenCount] = useState(0);
  const [unassignedCount, setUnassignedCount] = useState(0);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const toggleSidebar = useCallback(() => setSidebarOpen(prev => !prev), []);
  const openSidebar = useCallback(() => setSidebarOpen(true), []);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  const refreshStats = useCallback(async () => {
    try {
      const res = await emailAPI.stats();
      setUnreadCount(res.data.unread || 0);
      setOpenCount(res.data.open || 0);
      setUnassignedCount(res.data.unassigned || 0);
    } catch {}
  }, []);

  useEffect(() => {
    refreshStats();
    intervalRef.current = setInterval(refreshStats, 30000); // Poll every 30s
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [refreshStats]);

  return (
    <EmailContext.Provider value={{
      sidebarOpen, toggleSidebar, openSidebar, closeSidebar,
      unreadCount, openCount, unassignedCount, refreshStats,
    }}>
      {children}
    </EmailContext.Provider>
  );
}

export function useEmail() {
  return useContext(EmailContext);
}
