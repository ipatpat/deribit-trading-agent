import AccountForm from '../account/AccountForm';
import ReferralHint from '../account/ReferralHint';
import { useAccountsStore } from '../../stores/accounts';

interface DeribitStepProps {
  onSaved: (newId: string) => void;
}

function DeribitStep({ onSaved }: DeribitStepProps) {
  const endpoints = useAccountsStore((s) => s.endpoints);

  return (
    <div className="grid grid-cols-1 md:grid-cols-5 gap-8">
      {/* Left: form */}
      <div className="md:col-span-3">
        <h2 className="text-xl font-semibold text-primary mb-1">
          Add your Deribit account
        </h2>
        <p className="text-sm text-secondary mb-5">
          Connect your trading account so Vida and the dashboard can pull live data.
        </p>
        <AccountForm
          endpoints={endpoints}
          showEnvSwitcher
          primaryLabel="Save & Next"
          showCancel={false}
          onSaved={onSaved}
        />
      </div>

      {/* Right: help sidebar */}
      <aside className="md:col-span-2 space-y-5 text-sm">
        <section>
          <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-2">
            还没有 Deribit 账户？
          </div>
          <ReferralHint variant="inline" />
        </section>

        <section>
          <div className="text-overline text-secondary uppercase tracking-wider font-semibold mb-2">
            如何获取 API Key
          </div>
          <ol className="space-y-1.5 text-secondary list-decimal list-inside leading-relaxed">
            <li>登录 Deribit → <span className="text-primary">Account → API</span></li>
            <li>点击 <span className="text-primary">"Add new key"</span></li>
            <li>
              勾选 scopes：
              <div className="mt-1 ml-4 font-mono text-xs text-primary space-y-0.5">
                <div>• trade:read_write</div>
                <div>• account:read</div>
                <div>• wallet:read</div>
              </div>
            </li>
            <li>复制 Client ID 与 Client Secret 粘贴到左侧</li>
          </ol>
        </section>

        <section className="p-3 rounded-card bg-accent/[0.06] border border-accent/20">
          <div className="text-sm text-primary leading-relaxed">
            <span className="font-semibold">💡 建议</span><br />
            强烈建议先用 <span className="font-semibold">Paper Trade</span> 环境熟悉系统，确认无误后再切换到 Production。
          </div>
        </section>
      </aside>
    </div>
  );
}

export default DeribitStep;
