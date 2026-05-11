import { useEffect, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { useChatStore } from '../stores/chat';
import { useFuturesStore } from '../stores/futures';

interface Props {
  children: ReactNode;
}

function PageContextProvider({ children }: Props) {
  const { pathname } = useLocation();
  const futuresInstrument = useFuturesStore((s) => s.selectedInstrument);
  const setPageContext = useChatStore((s) => s.setPageContext);

  useEffect(() => {
    if (pathname === '/futures') {
      setPageContext({ route: pathname, instrument: futuresInstrument });
    } else {
      setPageContext({ route: pathname });
    }
  }, [pathname, futuresInstrument, setPageContext]);

  return <>{children}</>;
}

export default PageContextProvider;
