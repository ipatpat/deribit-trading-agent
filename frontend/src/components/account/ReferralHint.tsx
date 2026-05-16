import { ExternalLink } from 'lucide-react';

const DERIBIT_REFERRAL_URL = 'https://www.deribit.com/?reg=20899.657';

interface ReferralHintProps {
  /** `inline` is brighter (Welcome sidebar); `card` is muted (Settings card). */
  variant: 'inline' | 'card';
}

function ReferralHint({ variant }: ReferralHintProps) {
  if (variant === 'inline') {
    return (
      <a
        href={DERIBIT_REFERRAL_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 text-sm text-accent hover:text-accent/80 underline underline-offset-2 transition-colors"
      >
        通过推荐链接注册
        <ExternalLink size={12} />
      </a>
    );
  }

  // card: muted style for Settings
  return (
    <a
      href={DERIBIT_REFERRAL_URL}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1.5 text-overline text-secondary hover:text-primary transition-colors"
    >
      还没有 Deribit 账户？通过此链接注册
      <ExternalLink size={10} />
    </a>
  );
}

export default ReferralHint;
