import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        cream: {
          DEFAULT: '#F5F2EE', /* 暖石灰 Ground 层，和纸质感 */
          dark: '#EDE9E3',
          light: '#FFFFFF',
        },
        primary: '#1A1A1A', /* 接近纯黑，提供绝佳的阅读对比度 */
        secondary: '#8E8E93', /* 优雅的中间灰 */
        disabled: '#C7C7CC',
        divider: {
          DEFAULT: 'rgba(0, 0, 0, 0.08)', /* 可感知的分隔线 */
          strong: 'rgba(0, 0, 0, 0.12)',   /* 区域级分隔 */
        },
        accent: '#F05C00',
        profit: '#34C759', /* 苹果风格的绿 */
        loss: '#FF3B30',   /* 苹果风格的红 */
        'profit-bg': 'rgba(52, 199, 89, 0.1)',
        'loss-bg': 'rgba(255, 59, 48, 0.1)',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Display"', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'sans-serif'],
        mono: ['"SF Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      maxWidth: {
        content: '1468px',
      },
      spacing: {
        sidebar: '64px',
        topbar: '56px',
        smartbar: '64px',
        panel: '400px',
        'chat-fab': '48px',
        'chat-sidebar': '360px',
        'fab-bottom': '80px',
        'fab-right': '24px',
        'layout-gutter': '24px',
        'right-col-futures': '360px',
        'right-col-futures-compact': '280px',
      },
      fontSize: {
        xs: ['var(--font-size-xs)', { lineHeight: '1.25rem' }],
        sm: ['var(--font-size-sm)', { lineHeight: '1.25rem' }],
        base: ['var(--font-size-base)', { lineHeight: '1.5rem' }],
        lg: ['var(--font-size-lg)', { lineHeight: '1.75rem' }],
        xl: ['var(--font-size-xl)', { lineHeight: '1.75rem' }],
        '2xl': ['var(--font-size-2xl)', { lineHeight: '2rem' }],
        '3xl': ['var(--font-size-3xl)', { lineHeight: '2.25rem' }],
        overline: ['10px', { lineHeight: '12px', letterSpacing: '0.05em' }],
      },
      borderRadius: {
        card: '12px',
      },
      boxShadow: {
        card: '0px 12px 38px rgba(97,121,136,0.1), 0px 12px 203px rgba(25,48,72,0.1)',
        popup: '0px 24px 80px rgba(25,48,72,0.15)',
      },
    },
  },
  plugins: [],
} satisfies Config
