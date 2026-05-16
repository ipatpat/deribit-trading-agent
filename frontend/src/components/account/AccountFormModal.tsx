import { type AccountSummary, type EndpointInfo } from '../../api/accounts';
import AccountForm from './AccountForm';

interface Props {
  open: boolean;
  /** When set, the modal is in edit mode; only alias + secret are mutable. */
  account?: AccountSummary | null;
  endpoints: EndpointInfo[];
  onClose: () => void;
  onSaved?: (id: string) => void;
}

function AccountFormModal({ open, account, endpoints, onClose, onSaved }: Props) {
  if (!open) return null;
  const editing = !!account;

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-card shadow-card w-full max-w-md p-5">
        <div className="text-lg font-semibold text-primary mb-4">
          {editing ? `Edit "${account!.alias}"` : 'Add account'}
        </div>
        <AccountForm
          account={account}
          endpoints={endpoints}
          primaryLabel={editing ? 'Save' : 'Create'}
          onSaved={(id) => {
            onSaved?.(id);
            onClose();
          }}
          onCancel={onClose}
        />
      </div>
    </div>
  );
}

export default AccountFormModal;
