import type { AppProps } from 'next/app';
import { useEffect } from 'react';
import { AuthProvider } from '../contexts/AuthContext';
import '../styles/globals.css';
import '../styles/mission-control.css'; // MISSION CONTROL THEME — remove this line to revert

export default function App({ Component, pageProps }: AppProps) {
  useEffect(() => { document.body.classList.add('mission-control'); }, []); // MISSION CONTROL TOGGLE — remove this line to revert
  return (
    <AuthProvider>
      <Component {...pageProps} />
    </AuthProvider>
  );
}
