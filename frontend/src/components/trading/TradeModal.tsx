import * as Dialog from '@radix-ui/react-dialog';
import PayoffBuilder from './PayoffBuilder';
import { type PayoffLeg } from '../../api/client';

interface TradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  legs: PayoffLeg[];
  onRemoveLeg: (index: number) => void;
  onToggleDirection: (index: number) => void;
  onChangeAmount: (index: number, amount: number) => void;
  onTradeLeg?: (instrument: string, direction: 'buy' | 'sell') => void;
}

function TradeModal({
  isOpen,
  onClose,
  legs,
  onRemoveLeg,
  onToggleDirection,
  onChangeAmount,
  onTradeLeg,
}: TradeModalProps) {
  return (
    <Dialog.Root open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/20 backdrop-blur-sm z-50 transition-opacity" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-white w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-xl shadow-popup p-6 z-50 outline-none flex flex-col gap-6">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-xl font-semibold text-primary">
              Review Trade & Payoff
            </Dialog.Title>
            <Dialog.Close className="w-8 h-8 flex items-center justify-center rounded-full text-secondary hover:bg-cream hover:text-primary transition-colors outline-none">
              ✕
            </Dialog.Close>
          </div>

          <div className="flex-1">
            <PayoffBuilder
              legs={legs}
              onRemoveLeg={onRemoveLeg}
              onToggleDirection={onToggleDirection}
              onChangeAmount={onChangeAmount}
              onTradeLeg={onTradeLeg}
            />
          </div>

          <div className="flex justify-end pt-4 border-t border-divider">
            <button
              onClick={onClose}
              className="px-6 py-2 rounded text-sm font-medium text-secondary hover:text-primary transition-colors mr-2"
            >
              Cancel
            </button>
            <button
              className="px-8 py-2 bg-primary text-white rounded text-sm font-bold shadow-sm hover:bg-primary/90 transition-colors"
              onClick={() => {
                // Implement multi-leg combo order
                alert('Combo ordering to be implemented');
              }}
            >
              Submit Order
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default TradeModal;
