import { Wrench } from 'lucide-react';

function Risk() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-16 h-16 rounded-full bg-accent/10 flex items-center justify-center mb-5">
        <Wrench size={28} className="text-accent" />
      </div>
      <h1 className="text-xl font-semibold text-primary">Risk Management</h1>
      <p className="mt-2 text-sm text-secondary">正在开发中 · Coming soon</p>
      <p className="mt-5 max-w-md text-sm text-secondary leading-relaxed">
        风控面板正在重新设计。下一版将引入风险预算视图、阶梯式 drawdown 响应与压力测试预演。
      </p>
    </div>
  );
}

export default Risk;
