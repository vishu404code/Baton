/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        app: '#0B0C0F',
        sidebar: '#111217',
        main: '#16171D',
        raised: '#1D1F27',
        border: '#2A2D37',
        primary: '#E6E7EB',
        muted: '#8B8FA3',
        accent: '#6366F1',
        approved: '#22C55E',
        stale: '#F59E0B',
        rejected: '#EF4444',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
};
