import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

export type ThemeId = 'mission-control' | 'sakura-pink' | 'apple-clean' | 'blue-white';

export interface ThemeOption {
  id: ThemeId;
  name: string;
  description: string;
  preview: string; // CSS color swatch
}

export const THEMES: ThemeOption[] = [
  {
    id: 'mission-control',
    name: 'Mission Control',
    description: 'Dark navy with cyan accents',
    preview: '#0a0e1a',
  },
  {
    id: 'sakura-pink',
    name: 'Pink',
    description: 'Light pink and white',
    preview: '#fdf2f8',
  },
  {
    id: 'apple-clean',
    name: 'Clean',
    description: 'Light, minimal, modern',
    preview: '#f5f5f7',
  },
  {
    id: 'blue-white',
    name: 'Classic',
    description: 'Clean blue and white',
    preview: '#1e40af',
  },
];

interface ThemeContextType {
  theme: ThemeId;
  setTheme: (t: ThemeId) => void;
  themes: ThemeOption[];
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

function getStorageKey(userId?: number) {
  return userId ? `bci-theme-${userId}` : 'bci-theme-guest';
}

export const ThemeProvider: React.FC<{ children: React.ReactNode; userId?: number }> = ({
  children,
  userId,
}) => {
  const [theme, setThemeState] = useState<ThemeId>('mission-control');

  // Load saved theme on mount / user change
  useEffect(() => {
    try {
      const saved = localStorage.getItem(getStorageKey(userId)) as ThemeId | null;
      if (saved && THEMES.some((t) => t.id === saved)) {
        setThemeState(saved);
      } else {
        setThemeState('mission-control');
      }
    } catch {
      setThemeState('mission-control');
    }
  }, [userId]);

  // Apply theme classes to body whenever theme changes
  useEffect(() => {
    const body = document.body;

    // Always add mission-control as the base dark layer
    // (apple-clean and blue-white will override it with their own light backgrounds)
    body.classList.add('mission-control');

    // Remove all theme overlay classes
    THEMES.forEach((t) => {
      if (t.id !== 'mission-control') {
        body.classList.remove(t.id);
      }
    });

    // Add the active overlay class (if not base)
    if (theme !== 'mission-control') {
      body.classList.add(theme);
    }
  }, [theme]);

  const setTheme = useCallback(
    (t: ThemeId) => {
      setThemeState(t);
      try {
        localStorage.setItem(getStorageKey(userId), t);
      } catch {}
    },
    [userId]
  );

  return (
    <ThemeContext.Provider value={{ theme, setTheme, themes: THEMES }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};
