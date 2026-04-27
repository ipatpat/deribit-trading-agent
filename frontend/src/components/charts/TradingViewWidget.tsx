import { useEffect, useRef } from 'react';

interface TradingViewWidgetProps {
  symbol: string; // e.g. "DERIBIT:BTCUSD.P"
  height?: number | string;
}

function TradingViewWidget({ symbol, height = 500 }: TradingViewWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Clear previous widget
    containerRef.current.innerHTML = '';

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.type = 'text/javascript';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol,
      interval: '15',
      timezone: 'Etc/UTC',
      theme: 'light',
      style: '1',
      locale: 'en',
      backgroundColor: '#FFFFFF',
      gridColor: '#F0EDE6',
      hide_top_toolbar: false,
      hide_legend: false,
      allow_symbol_change: false,
      save_image: false,
      calendar: false,
      hide_volume: false,
      support_host: 'https://www.tradingview.com',
    });

    containerRef.current.appendChild(script);

    return () => {
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
  }, [symbol]);

  return (
    <div className="tradingview-widget-container" style={{ height }}>
      <div ref={containerRef} style={{ height: '100%', width: '100%' }} />
    </div>
  );
}

export default TradingViewWidget;
