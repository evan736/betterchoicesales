import React, { useState } from 'react';
import { MapPin, Users, TrendingUp } from 'lucide-react';

// Simplified US state paths for SVG map (viewBox 0 0 960 600)
const STATE_PATHS: Record<string, string> = {
  AL: "M628,425 L628,468 L624,491 L631,492 L631,499 L619,499 L614,491 L610,469 L610,425Z",
  AK: "M161,485 L183,485 L183,516 L161,516Z",
  AZ: "M205,390 L205,455 L243